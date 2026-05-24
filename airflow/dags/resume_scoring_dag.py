"""Nightly resume AI-detection scoring DAG — Sprint 15.

Schedule: daily at 03:00 UTC (cron ``0 3 * * *``).
Staggered 1 hour after the retraining DAG (``0 2 * * *``) to avoid
competing for MinIO / CPU resources.

Task graph:
    scan_pending_resumes
             │
             ▼
        score_resumes
             │
             ▼
       persist_scores
             │
             ▼
       notify_resume

All four task callables are plain Python functions defined BEFORE the DAG
scaffold so unit and integration tests can import and invoke them directly
without a live Airflow installation.

Dependency-injection pattern:
  - ``score_resume_batch(..., _engine=None, _perp_scorer=None, _unif_model=None)``
    accepts optional ML stubs to avoid model downloads during tests.
  - ``scan_pending_resumes_in_window(..., _store=None)`` accepts an optional
    ObjectStore stub for test injection.
  - ``persist_resume_scores(..., _spark=None)`` accepts an optional
    SparkSession stub for test injection.

Hard rules from CLAUDE.md:
  - No PII in logs (candidate_uuid UUID only — resume text is never logged).
  - ML model updates require a DAG run — never triggered ad-hoc (§8.5).
  - retries=2, retry_delay=timedelta(minutes=5) on every task (via DEFAULT_ARGS).
  - flag_reason must never be empty for flagged candidates (enforced by
    ResumeScoreEngine.compute — §8.2).
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timezone
from typing import Any

import structlog

import config
from ingestion.resume_parser import parse_resume
from ml.features.resume_burstiness import score_resume_burstiness
from ml.features.resume_perplexity import score_resume_perplexity
from ml.features.section_uniformity import score_section_uniformity
from ml.features.vocab_richness import score_vocab_richness
from ml.resume_score import ResumeScoreEngine
from storage.object_store import BUCKET_RESUMES, ObjectStore

logger = structlog.get_logger(__name__)

_RESUME_SCORES_TABLE = "resume_scores"


# ── MinIO factory (patchable in tests) ────────────────────────────────────────

def _make_object_store() -> ObjectStore:
    return ObjectStore(
        endpoint=config.MINIO_ENDPOINT,
        access_key=config.MINIO_ACCESS_KEY,
        secret_key=config.MINIO_SECRET_KEY,
    )


# ── Helper functions (pure, testable without Airflow) ─────────────────────────

def scan_pending_resumes_in_window(
    from_ts: float,
    to_ts: float,
    _store: Any = None,
) -> list[dict[str, Any]]:
    """List resume objects uploaded within [from_ts, to_ts).

    Walks MinIO ``resumes/`` bucket and returns metadata for objects whose
    ``last_modified`` timestamp falls in the given half-open interval.

    Args:
        from_ts: Inclusive lower bound (Unix timestamp).
        to_ts: Exclusive upper bound (Unix timestamp).
        _store: Optional ObjectStore stub for test injection.

    Returns:
        List of dicts with keys: candidate_uuid, minio_path, file_ext.
        Returns an empty list on MinIO error (never raises).
    """
    store = _store or _make_object_store()
    pending: list[dict[str, Any]] = []

    try:
        objects = store._client.list_objects(BUCKET_RESUMES, recursive=True)
        for obj in objects:
            if obj.last_modified is None:
                continue
            ts = obj.last_modified.timestamp()
            if from_ts <= ts < to_ts:
                # Object name: resumes/{candidate_uuid}/{timestamp_iso}.{ext}
                parts = obj.object_name.split("/")
                if len(parts) == 3:
                    candidate_uuid = parts[1]
                    filename = parts[2]
                    file_ext = filename.rsplit(".", 1)[-1] if "." in filename else "txt"
                    pending.append({
                        "candidate_uuid": candidate_uuid,
                        "minio_path": obj.object_name,
                        "file_ext": file_ext,
                    })
    except Exception as exc:
        logger.warning("minio_resume_scan_failed", error=str(exc))

    logger.info(
        "resumes_scanned",
        count=len(pending),
        from_ts=from_ts,
        to_ts=to_ts,
    )
    return pending


def score_resume_batch(
    pending: list[dict[str, Any]],
    _store: Any = None,
    _engine: Any = None,
    _perp_scorer: Any = None,
    _unif_model: Any = None,
) -> list[dict[str, Any]]:
    """Download, parse, and score each pending resume.

    For each item in ``pending``:
      1. Download raw bytes from MinIO.
      2. Parse via ``parse_resume()`` (PDF / DOCX / TXT).
      3. Run all four signal scorers.
      4. Aggregate via ``ResumeScoreEngine.compute()``.

    Items that fail to download or parse are logged and skipped; they do
    not block the rest of the batch.

    Args:
        pending: List of ``{candidate_uuid, minio_path, file_ext}`` dicts.
        _store: Optional ObjectStore stub for test injection.
        _engine: Optional ResumeScoreEngine stub for test injection.
        _perp_scorer: Optional PerplexityScorer stub for test injection.
        _unif_model: Optional SentenceTransformer stub for test injection.

    Returns:
        List of serialised ResumeScoreResult dicts (via dataclasses.asdict).
    """
    store = _store or _make_object_store()
    engine = _engine or ResumeScoreEngine()
    results: list[dict[str, Any]] = []

    for item in pending:
        candidate_uuid = item["candidate_uuid"]
        minio_path = item["minio_path"]
        file_ext = item["file_ext"]

        try:
            response = store._client.get_object(BUCKET_RESUMES, minio_path)
            data = response.read()
            response.close()
        except Exception as exc:
            logger.warning(
                "resume_download_failed",
                candidate_uuid=candidate_uuid,   # UUID — no PII
                error=str(exc),
            )
            continue

        try:
            parsed = parse_resume(candidate_uuid, file_ext, data)
        except Exception as exc:
            logger.warning(
                "resume_parse_failed",
                candidate_uuid=candidate_uuid,   # UUID — no PII
                file_ext=file_ext,
                error=str(exc),
            )
            continue

        perp = score_resume_perplexity(
            candidate_uuid, parsed.sections, _scorer=_perp_scorer
        )
        burst = score_resume_burstiness(candidate_uuid, parsed.sections)
        vocab = score_vocab_richness(candidate_uuid, parsed.full_text)
        unif = score_section_uniformity(
            candidate_uuid, parsed.sections, _model=_unif_model
        )

        score_result = engine.compute(
            candidate_uuid=candidate_uuid,
            perplexity_score=perp.suspicion_score,
            burstiness_score=burst.suspicion_score,
            vocab_richness_score=vocab.suspicion_score,
            section_uniformity_score=unif.suspicion_score,
        )

        results.append(dataclasses.asdict(score_result))

    logger.info(
        "resume_batch_scored",
        total=len(pending),
        scored=len(results),
        flagged=sum(1 for r in results if r.get("flagged")),
    )
    return results


def persist_resume_scores(
    score_dicts: list[dict[str, Any]],
    delta_lake_path: str,
    _spark: Any = None,
) -> int:
    """Append resume scores to the Delta Lake resume_scores table.

    Scores are append-only — each run appends new rows identified by
    (candidate_uuid, scored_at). Historical scores are preserved for audit.

    Args:
        score_dicts: Serialised ResumeScoreResult dicts from score_resume_batch.
        delta_lake_path: Base path for Delta Lake tables.
        _spark: Optional SparkSession for test injection.

    Returns:
        Number of rows written; 0 on error (never raises).
    """
    if not score_dicts:
        return 0

    try:
        from pyspark.sql import SparkSession
        from pyspark.sql.types import (
            BooleanType,
            DoubleType,
            StringType,
            StructField,
            StructType,
        )

        spark = _spark or (
            SparkSession.builder
            .appName("TrustSignal-ResumeScores")
            .config(
                "spark.sql.extensions",
                "io.delta.sql.DeltaSparkSessionExtension",
            )
            .config(
                "spark.sql.catalog.spark_catalog",
                "org.apache.spark.sql.delta.catalog.DeltaCatalog",
            )
            .getOrCreate()
        )

        schema = StructType([
            StructField("candidate_uuid",  StringType(),  False),
            StructField("resume_ai_score", DoubleType(),  False),
            StructField("suspicion_index", DoubleType(),  False),
            StructField("flagged",         BooleanType(), False),
            StructField("flag_reason",     StringType(),  True),
            StructField("signals_json",    StringType(),  True),
            StructField("scored_at",       DoubleType(),  False),
        ])

        rows = [
            (
                d["candidate_uuid"],
                float(d["resume_ai_score"]),
                float(d["suspicion_index"]),
                bool(d["flagged"]),
                d.get("flag_reason", ""),
                json.dumps(d.get("signals", [])),
                float(d["scored_at"]),
            )
            for d in score_dicts
        ]

        df = spark.createDataFrame(rows, schema=schema)
        table_path = f"{delta_lake_path}/{_RESUME_SCORES_TABLE}"
        df.write.format("delta").mode("append").save(table_path)

        logger.info(
            "resume_scores_persisted",
            count=len(rows),
            table=_RESUME_SCORES_TABLE,
        )
        return len(rows)

    except Exception as exc:
        logger.error("resume_scores_persist_failed", error=str(exc))
        return 0


def build_resume_slack_payload(stats: dict[str, Any]) -> dict[str, Any]:
    """Build a Slack Block Kit payload for the resume scoring run.

    Args:
        stats: Keys: resumes_scanned, resumes_scored, flagged_count,
               persisted_count, dag_run_date.

    Returns:
        Dict suitable for JSON-posting to a Slack Incoming Webhook.
    """
    scanned = int(stats.get("resumes_scanned", 0))
    scored = int(stats.get("resumes_scored", 0))
    flagged = int(stats.get("flagged_count", 0))
    persisted = int(stats.get("persisted_count", 0))
    date = str(stats.get("dag_run_date", ""))

    status_icon = ":shield:" if flagged > 0 else ":white_check_mark:"

    return {
        "text": f"{status_icon} TrustSignal Resume Scoring — {date}",
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"TrustSignal Resume Scoring — {date}",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Resumes scanned:*\n{scanned}"},
                    {"type": "mrkdwn", "text": f"*Resumes scored:*\n{scored}"},
                    {"type": "mrkdwn", "text": f"*Flagged (AI-suspected):*\n{flagged}"},
                    {"type": "mrkdwn", "text": f"*Scores persisted:*\n{persisted}"},
                ],
            },
        ],
    }


# ── Airflow task callables ─────────────────────────────────────────────────────
# These accept a standard Airflow **context dict. Importable without Airflow.

def _scan_pending_resumes(**context: Any) -> dict[str, Any]:
    """Task 1: list resumes uploaded during the DAG data interval."""
    from_ts = context["data_interval_start"].timestamp()
    to_ts = context["data_interval_end"].timestamp()

    pending = scan_pending_resumes_in_window(from_ts, to_ts)
    return {"pending": pending, "count": len(pending)}


def _score_resumes(**context: Any) -> dict[str, Any]:
    """Task 2: download, parse, and score all pending resumes."""
    ti = context["ti"]
    result = ti.xcom_pull(task_ids="scan_pending_resumes") or {}
    pending: list[dict[str, Any]] = result.get("pending", [])

    score_dicts = score_resume_batch(pending)
    flagged_count = sum(1 for d in score_dicts if d.get("flagged"))

    return {
        "score_dicts": score_dicts,
        "scored_count": len(score_dicts),
        "flagged_count": flagged_count,
    }


def _persist_scores(**context: Any) -> dict[str, Any]:
    """Task 3: write scores to the Delta Lake resume_scores table."""
    ti = context["ti"]
    result = ti.xcom_pull(task_ids="score_resumes") or {}
    score_dicts: list[dict[str, Any]] = result.get("score_dicts", [])

    n_persisted = persist_resume_scores(score_dicts, config.DELTA_LAKE_PATH)
    return {"persisted_count": n_persisted}


def _notify_resume(**context: Any) -> None:
    """Task 4: send Slack summary of the completed scoring run.

    Pulls XCom results from upstream tasks, builds a Block Kit payload,
    and POSTs it to SLACK_WEBHOOK_URL. If the env variable is unset, the
    summary is logged instead (never raises).
    """
    ti = context["ti"]

    scan_r = ti.xcom_pull(task_ids="scan_pending_resumes") or {}
    score_r = ti.xcom_pull(task_ids="score_resumes") or {}
    persist_r = ti.xcom_pull(task_ids="persist_scores") or {}

    stats: dict[str, Any] = {
        "resumes_scanned": scan_r.get("count", 0),
        "resumes_scored": score_r.get("scored_count", 0),
        "flagged_count": score_r.get("flagged_count", 0),
        "persisted_count": persist_r.get("persisted_count", 0),
        "dag_run_date": context.get("ds", ""),
    }

    webhook_url = getattr(config, "SLACK_WEBHOOK_URL", "") or ""

    if webhook_url:
        import requests as _requests
        payload = build_resume_slack_payload(stats)
        try:
            resp = _requests.Session().post(webhook_url, json=payload, timeout=10)
            resp.raise_for_status()
            logger.info("resume_slack_notification_sent")
        except Exception as exc:
            logger.error("resume_slack_notification_failed", error=str(exc))
    else:
        logger.info("resume_slack_webhook_not_configured", stats=stats)


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
        dag_id="trustsignal_resume_scoring",
        default_args=DEFAULT_ARGS,
        description=(
            "Nightly AI-detection scoring of uploaded candidate resumes. "
            "Per CLAUDE.md: ML scoring runs via this DAG — never ad-hoc."
        ),
        schedule_interval="0 3 * * *",
        start_date=datetime(2026, 1, 1),
        catchup=False,
        tags=["ml", "resume", "prescreening", "trustsignal"],
    ) as dag:

        t_scan = _PythonOperator(
            task_id="scan_pending_resumes",
            python_callable=_scan_pending_resumes,
        )

        t_score = _PythonOperator(
            task_id="score_resumes",
            python_callable=_score_resumes,
        )

        t_persist = _PythonOperator(
            task_id="persist_scores",
            python_callable=_persist_scores,
        )

        t_notify = _PythonOperator(
            task_id="notify_resume",
            python_callable=_notify_resume,
        )

        # Linear dependency: scan → score → persist → notify
        t_scan >> t_score >> t_persist >> t_notify

except ImportError:
    # apache-airflow not installed (e.g. unit-test environment).
    # Business logic helpers and callables remain importable and testable.
    pass
