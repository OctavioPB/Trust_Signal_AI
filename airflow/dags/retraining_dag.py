"""Nightly model retraining DAG — Sprint 9.

Schedule: daily at 02:00 UTC (cron ``0 2 * * *``).

Task graph:
    extract_suspicious
         │
         ▼
    compute_embeddings
         │
         ▼
    retrain_bg_classifier ──► update_answer_bank
         │                            │
         └──────────┬─────────────────┘
                    ▼
                  notify

All five task callables are plain Python functions that accept an Airflow
``**context`` dict. They are defined BEFORE the DAG scaffold so that unit and
integration tests can import and invoke them directly with a mocked context,
without requiring a live Airflow installation.

Dependency-injection pattern:
  - ``query_suspicious_segments(..., _conn=None)`` accepts an optional DuckDB
    connection for testing.
  - ``embed_texts(..., _model=None)`` accepts an optional SentenceTransformer
    stub for testing.
  - ``send_slack_notification(..., _session=None)`` accepts an optional
    requests.Session for testing.
  - The MinIO client is created via the module-level ``_make_object_store()``
    factory, which tests patch via ``unittest.mock.patch``.

Hard rules from CLAUDE.md:
  - No PII in logs (session_id UUID only; segment text is never logged).
  - ML model updates require a DAG run — never triggered ad-hoc.
  - retries=2, retry_delay=timedelta(minutes=5) on every task (via DEFAULT_ARGS).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from itertools import groupby
from pathlib import Path
from typing import Any

import numpy as np
import requests as _requests
import structlog

import config
from ml.embeddings.similarity import ANSWER_BANK_PATH
from ml.features.audio_bg import BackgroundAudioClassifier
from storage.object_store import BUCKET_RAW_AUDIO, ObjectStore

logger = structlog.get_logger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

_EMBEDDING_MODEL      = "all-MiniLM-L6-v2"
_EMBEDDINGS_FILE      = "embeddings.npy"
_METADATA_FILE        = "metadata.json"
_MIN_RETRAIN_SAMPLES  = 10    # skip retraining if fewer new labeled samples
_MAX_AUDIO_PER_SESSION = 20   # cap audio chunks per session (memory guard)


# ── MinIO factory (patchable in tests) ────────────────────────────────────────

def _make_object_store() -> ObjectStore:
    return ObjectStore(
        endpoint=config.MINIO_ENDPOINT,
        access_key=config.MINIO_ACCESS_KEY,
        secret_key=config.MINIO_SECRET_KEY,
    )


# ── Helper functions (pure, testable without Airflow) ─────────────────────────

def query_suspicious_segments(
    delta_lake_path: str,
    from_ts: float,
    to_ts: float,
    _conn: Any = None,
) -> list[dict[str, Any]]:
    """Query Delta Lake for suspicious segments in the given time window.

    Uses DuckDB to scan Parquet files produced by DeltaWriter. Returns an
    empty list (never raises) when the Delta table does not yet exist or
    the query fails, so early-stage deployments don't crash the DAG.

    Args:
        delta_lake_path: Base path to the Delta Lake store (DELTA_LAKE_PATH).
        from_ts: Inclusive lower bound Unix timestamp.
        to_ts: Exclusive upper bound Unix timestamp.
        _conn: Optional DuckDB connection for test injection.

    Returns:
        List of dicts with keys: session_id, chunk_seq, speaker, text,
        start_ts, end_ts.
    """
    import duckdb

    conn = _conn or duckdb.connect()
    parquet_glob = f"{delta_lake_path}/transcript_segments/**/*.parquet"

    try:
        rows = conn.execute(
            """
            SELECT session_id, chunk_seq, speaker, text, start_ts, end_ts
            FROM parquet_scan(?)
            WHERE suspicious_flag = true
              AND start_ts >= ?
              AND start_ts <  ?
            ORDER BY session_id, start_ts
            """,
            [parquet_glob, from_ts, to_ts],
        ).fetchall()
    except Exception as exc:
        logger.warning(
            "delta_query_failed",
            delta_lake_path=delta_lake_path,
            error=str(exc),
        )
        return []

    columns = ["session_id", "chunk_seq", "speaker", "text", "start_ts", "end_ts"]
    return [dict(zip(columns, row)) for row in rows]


def embed_texts(
    texts: list[str],
    model_name: str = _EMBEDDING_MODEL,
    _model: Any = None,
) -> np.ndarray:
    """Embed a list of texts using Sentence-Transformers.

    Args:
        texts: List of candidate transcript segments to embed.
        model_name: Sentence-Transformers model identifier.
        _model: Optional pre-built model stub (test injection).

    Returns:
        float32 numpy array of shape (len(texts), embedding_dim).
        Returns shape (0, 384) for empty input.
    """
    if not texts:
        return np.zeros((0, 384), dtype=np.float32)

    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(model_name)

    embeddings = _model.encode(
        texts,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return np.asarray(embeddings, dtype=np.float32)


def update_vector_store(
    store_path: str,
    new_embeddings: np.ndarray,
    new_texts: list[str],
) -> int:
    """Append new embeddings to the on-disk vector store.

    The store consists of two files:
      - ``embeddings.npy`` — float32 array of shape (N, D).
      - ``metadata.json`` — list of {text, ts} objects.

    Args:
        store_path: Directory path for the vector store (VECTOR_STORE_PATH).
        new_embeddings: float32 array of shape (n_new, D).
        new_texts: Parallel list of texts for the new embeddings.

    Returns:
        Number of new vectors appended.
    """
    if len(new_texts) == 0:
        return 0

    path = Path(store_path)
    path.mkdir(parents=True, exist_ok=True)

    emb_file  = path / _EMBEDDINGS_FILE
    meta_file = path / _METADATA_FILE
    now_iso   = datetime.now(tz=timezone.utc).isoformat()
    new_meta  = [{"text": t, "ts": now_iso} for t in new_texts]

    if emb_file.exists() and meta_file.exists():
        existing_emb  = np.load(str(emb_file))
        with meta_file.open(encoding="utf-8") as f:
            existing_meta = json.load(f)
        combined_emb  = np.vstack([existing_emb, new_embeddings])
        combined_meta = existing_meta + new_meta
    else:
        combined_emb  = new_embeddings
        combined_meta = new_meta

    np.save(str(emb_file), combined_emb.astype(np.float32))
    with meta_file.open("w", encoding="utf-8") as f:
        json.dump(combined_meta, f, ensure_ascii=False, indent=None)

    n_added = len(new_texts)
    logger.info("vector_store_updated", added=n_added, total=len(combined_meta))
    return n_added


def make_qa_pairs(segments: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Extract Q&A pairs from consecutive RECRUITER → CANDIDATE segment runs.

    Segments are grouped by session_id, sorted by start_ts. For each
    CANDIDATE segment immediately following a RECRUITER segment, a Q&A
    pair ``{question: ..., answer: ...}`` is produced.

    Args:
        segments: List of segment dicts from ``query_suspicious_segments``.

    Returns:
        List of ``{question, answer}`` dicts suitable for the answer bank.
    """
    sorted_segs = sorted(
        segments,
        key=lambda s: (s["session_id"], float(s["start_ts"])),
    )

    pairs: list[dict[str, str]] = []
    for _, group in groupby(sorted_segs, key=lambda s: s["session_id"]):
        session_segs = list(group)
        for i, seg in enumerate(session_segs):
            if seg["speaker"].upper() == "CANDIDATE" and i > 0:
                prev = session_segs[i - 1]
                if prev["speaker"].upper() == "RECRUITER":
                    pairs.append({
                        "question": str(prev["text"]),
                        "answer":   str(seg["text"]),
                    })
    return pairs


def append_answer_bank(bank_path: str, new_pairs: list[dict[str, str]]) -> int:
    """Append unique new Q&A pairs to the JSONL answer bank.

    Deduplicates on the ``answer`` field so the bank never accumulates
    duplicate AI-generated answers. New pairs are appended line-by-line.

    Args:
        bank_path: Path to ``llm_answer_bank.jsonl``.
        new_pairs: Q&A dicts from ``make_qa_pairs``.

    Returns:
        Number of lines actually written (deduplicates against existing).
    """
    path = Path(bank_path)
    existing_answers: set[str] = set()

    if path.exists():
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    existing_answers.add(obj.get("answer", ""))
                except json.JSONDecodeError:
                    pass

    n_appended = 0
    with path.open("a", encoding="utf-8") as f:
        for pair in new_pairs:
            answer = pair.get("answer", "").strip()
            if answer and answer not in existing_answers:
                f.write(json.dumps(pair, ensure_ascii=False) + "\n")
                existing_answers.add(answer)
                n_appended += 1

    if n_appended:
        logger.info("answer_bank_updated", pairs_appended=n_appended)
    return n_appended


def build_slack_payload(stats: dict[str, Any]) -> dict[str, Any]:
    """Build a Slack Block Kit payload from DAG run statistics.

    Args:
        stats: Keys: segments_extracted, embeddings_added, retrained,
               artifact_name, pairs_appended, dag_run_date.

    Returns:
        Dict suitable for JSON-posting to a Slack Incoming Webhook.
    """
    segments   = int(stats.get("segments_extracted", 0))
    embeddings = int(stats.get("embeddings_added", 0))
    retrained  = bool(stats.get("retrained", False))
    artifact   = str(stats.get("artifact_name", "—"))
    pairs      = int(stats.get("pairs_appended", 0))
    date       = str(stats.get("dag_run_date", ""))

    classifier_text = (
        f"Retrained — artifact: `{artifact}`"
        if retrained
        else "Skipped (insufficient new samples)"
    )
    status_icon = ":white_check_mark:" if segments > 0 else ":information_source:"

    return {
        "text": f"{status_icon} TrustSignal Nightly Retraining — {date}",
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type":  "plain_text",
                    "text":  f"TrustSignal Nightly Retraining — {date}",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Suspicious segments extracted:*\n{segments}"},
                    {"type": "mrkdwn", "text": f"*Embeddings added to vector store:*\n{embeddings}"},
                    {"type": "mrkdwn", "text": f"*Answer bank pairs appended:*\n{pairs}"},
                    {"type": "mrkdwn", "text": f"*Background audio classifier:*\n{classifier_text}"},
                ],
            },
        ],
    }


def send_slack_notification(
    webhook_url: str,
    payload: dict[str, Any],
    _session: Any = None,
) -> bool:
    """POST a Block Kit payload to a Slack Incoming Webhook.

    Errors are logged but never re-raised so DAG failures in the notify
    task never cascade to an alert storm.

    Args:
        webhook_url: Slack Incoming Webhook URL (from SLACK_WEBHOOK_URL env).
        payload: Block Kit dict from ``build_slack_payload``.
        _session: Optional requests.Session for test injection.

    Returns:
        True on HTTP 200, False otherwise.
    """
    session = _session or _requests.Session()
    try:
        resp = session.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
        logger.info("slack_notification_sent")
        return True
    except Exception as exc:
        logger.error("slack_notification_failed", error=str(exc))
        return False


# ── Airflow task callables ─────────────────────────────────────────────────────
# These functions accept a standard Airflow **context dict and return a dict
# that Airflow XComs. They are testable with a mock context (no live Airflow).

def _extract_suspicious(**context: Any) -> dict[str, Any]:
    """Task 1: query Delta Lake for suspicious segments from the past DAG interval."""
    from_ts = context["data_interval_start"].timestamp()
    to_ts   = context["data_interval_end"].timestamp()

    segments = query_suspicious_segments(
        config.DELTA_LAKE_PATH, from_ts, to_ts
    )

    logger.info(
        "suspicious_segments_extracted",
        count=len(segments),
        from_ts=from_ts,
        to_ts=to_ts,
    )
    return {"segments": segments, "count": len(segments)}


def _compute_embeddings(**context: Any) -> dict[str, Any]:
    """Task 2: batch-embed suspicious CANDIDATE segments; update vector store."""
    ti      = context["ti"]
    result  = ti.xcom_pull(task_ids="extract_suspicious") or {}
    segments: list[dict[str, Any]] = result.get("segments", [])

    candidate_texts = [
        s["text"] for s in segments
        if s.get("speaker", "").upper() == "CANDIDATE"
    ]

    if not candidate_texts:
        logger.info("compute_embeddings_skipped", reason="no_candidate_segments")
        return {"embeddings_added": 0}

    embeddings = embed_texts(candidate_texts)
    n_added    = update_vector_store(
        config.VECTOR_STORE_PATH, embeddings, candidate_texts
    )

    logger.info("embeddings_computed", n_texts=len(candidate_texts), n_added=n_added)
    return {"embeddings_added": n_added}


def _retrain_bg_classifier(**context: Any) -> dict[str, Any]:
    """Task 3: retrain the background audio classifier from suspicious sessions.

    Downloads raw audio chunks from MinIO for sessions that appear in the
    suspicious segment list, extracts MFCC features, and retrains. If fewer
    than ``_MIN_RETRAIN_SAMPLES`` new samples are gathered, retraining is
    skipped gracefully (retrained=False in the return payload).

    The versioned artifact is uploaded to model-artifacts/{date}_bg_classifier.pkl.
    """
    ti           = context["ti"]
    result       = ti.xcom_pull(task_ids="extract_suspicious") or {}
    segments: list[dict[str, Any]] = result.get("segments", [])
    date_str     = context["ds_nodash"]                  # YYYYMMDD
    artifact_name = f"{date_str}_bg_classifier.pkl"

    # Unique session IDs with suspicious CANDIDATE turns
    suspicious_sessions = {
        s["session_id"]
        for s in segments
        if s.get("speaker", "").upper() == "CANDIDATE"
    }

    features: list[np.ndarray] = []
    labels:   list[int]        = []

    if suspicious_sessions:
        try:
            store = _make_object_store()
            for session_id in sorted(suspicious_sessions):
                chunk_paths = store.list_session_chunks(session_id)
                for obj_path in chunk_paths[:_MAX_AUDIO_PER_SESSION]:
                    try:
                        response = store._client.get_object(BUCKET_RAW_AUDIO, obj_path)
                        audio_bytes = response.read()
                        response.close()
                        audio_f32 = (
                            np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)
                            / 32768.0
                        )
                        from ml.features.audio_bg import extract_mfcc_features
                        feat = extract_mfcc_features(audio_f32)
                        features.append(feat)
                        labels.append(1)   # suspicious session → keyboard class
                    except Exception as chunk_exc:
                        logger.debug(
                            "audio_chunk_skipped",
                            session_id=session_id,
                            error=str(chunk_exc),
                        )
        except Exception as store_exc:
            logger.warning("minio_unavailable", error=str(store_exc))

    if len(features) < _MIN_RETRAIN_SAMPLES:
        logger.info(
            "retrain_skipped",
            n_samples=len(features),
            threshold=_MIN_RETRAIN_SAMPLES,
        )
        return {
            "artifact_name":  artifact_name,
            "samples_used":   len(features),
            "retrained":      False,
        }

    X = np.stack(features)
    y = np.array(labels, dtype=np.int32)

    clf = BackgroundAudioClassifier()
    clf.train_from_arrays(X, y)

    artifact_bytes = clf.to_bytes()

    try:
        store = _make_object_store()
        store.upload_model_artifact(artifact_name, artifact_bytes)
        logger.info("classifier_uploaded", name=artifact_name, samples=len(y))
    except Exception as upload_exc:
        logger.error("artifact_upload_failed", name=artifact_name, error=str(upload_exc))

    return {
        "artifact_name": artifact_name,
        "samples_used":  len(features),
        "retrained":     True,
    }


def _update_answer_bank(**context: Any) -> dict[str, Any]:
    """Task 4: extract Q&A pairs from suspicious segments and append to the bank."""
    ti      = context["ti"]
    result  = ti.xcom_pull(task_ids="extract_suspicious") or {}
    segments: list[dict[str, Any]] = result.get("segments", [])

    new_pairs = make_qa_pairs(segments)
    n_appended = append_answer_bank(str(ANSWER_BANK_PATH), new_pairs)

    logger.info(
        "answer_bank_update_done",
        pairs_found=len(new_pairs),
        pairs_appended=n_appended,
    )
    return {"pairs_appended": n_appended, "pairs_found": len(new_pairs)}


def _notify(**context: Any) -> None:
    """Task 5: send Slack summary of the completed DAG run.

    Pulls XCom results from all upstream tasks, builds a Block Kit payload,
    and POSTs it to SLACK_WEBHOOK_URL. If the env variable is not set, the
    summary is logged instead (never raises).
    """
    ti = context["ti"]

    extract_r  = ti.xcom_pull(task_ids="extract_suspicious")   or {}
    embed_r    = ti.xcom_pull(task_ids="compute_embeddings")    or {}
    retrain_r  = ti.xcom_pull(task_ids="retrain_bg_classifier") or {}
    bank_r     = ti.xcom_pull(task_ids="update_answer_bank")    or {}

    stats: dict[str, Any] = {
        "segments_extracted": extract_r.get("count",            0),
        "embeddings_added":   embed_r.get("embeddings_added",   0),
        "retrained":          retrain_r.get("retrained",        False),
        "artifact_name":      retrain_r.get("artifact_name",    "—"),
        "pairs_appended":     bank_r.get("pairs_appended",      0),
        "dag_run_date":       context.get("ds", ""),
    }

    webhook_url = getattr(config, "SLACK_WEBHOOK_URL", "") or ""

    if webhook_url:
        payload = build_slack_payload(stats)
        send_slack_notification(webhook_url, payload)
    else:
        logger.info("slack_webhook_not_configured", stats=stats)


# ── DAG scaffold (requires apache-airflow; guarded so module is importable) ────

try:
    from datetime import timedelta as _timedelta

    from airflow import DAG as _DAG
    from airflow.operators.python import PythonOperator as _PythonOperator

    DEFAULT_ARGS: dict[str, Any] = {
        "owner":            "trustsignal",
        "depends_on_past":  False,
        "retries":          2,
        "retry_delay":      _timedelta(minutes=5),
        "email_on_failure": False,
    }

    with _DAG(
        dag_id="trustsignal_nightly_retraining",
        default_args=DEFAULT_ARGS,
        description=(
            "Nightly retraining of ML signal modules from flagged transcripts. "
            "Per CLAUDE.md: ML model updates must run via this DAG — never ad-hoc."
        ),
        schedule_interval="0 2 * * *",
        start_date=datetime(2026, 1, 1),
        catchup=False,
        tags=["ml", "retraining", "trustsignal"],
    ) as dag:

        t_extract = _PythonOperator(
            task_id="extract_suspicious",
            python_callable=_extract_suspicious,
        )

        t_embed = _PythonOperator(
            task_id="compute_embeddings",
            python_callable=_compute_embeddings,
        )

        t_retrain = _PythonOperator(
            task_id="retrain_bg_classifier",
            python_callable=_retrain_bg_classifier,
        )

        t_bank = _PythonOperator(
            task_id="update_answer_bank",
            python_callable=_update_answer_bank,
        )

        t_notify = _PythonOperator(
            task_id="notify",
            python_callable=_notify,
        )

        # Task dependency graph
        t_extract >> t_embed >> t_retrain >> t_notify
        t_retrain >> t_bank >> t_notify

except ImportError:
    # apache-airflow not installed (e.g. unit-test environment).
    # Business logic helpers and callables remain importable and testable.
    pass
