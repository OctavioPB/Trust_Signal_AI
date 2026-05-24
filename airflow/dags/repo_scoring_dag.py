"""Nightly repository AI-detection scoring DAG — Sprint 17.

Schedule: daily at 04:00 UTC (cron ``0 4 * * *``).
Staggered 1 hour after the resume scoring DAG (``0 3 * * *``) to avoid
competing for MinIO / CPU / ML resources.

Task graph:
    scan_pending_repos
            │
            ▼
        score_repos
            │
            ▼
    persist_repo_scores
            │
            ▼
       notify_repo

All four task callables are plain Python functions defined BEFORE the DAG
scaffold so unit and integration tests can import and invoke them directly
without a live Airflow installation.

Dependency-injection pattern:
  - ``score_repos_batch(..., _engine=None, _ppl_scorer=None, _style_scorer=None)``
    accepts optional ML stubs to avoid model downloads during tests.
  - ``scan_pending_repos_in_window(..., _store=None)`` accepts an optional
    ObjectStore stub for test injection.
  - ``persist_repo_scores(..., _spark=None)`` accepts an optional SparkSession
    stub for test injection.

Hard rules from CLAUDE.md:
  - No PII in logs (repo_uuid UUID only — source code content is never logged).
  - ML model updates require a DAG run — never triggered ad-hoc (§8.5).
  - retries=2, retry_delay=timedelta(minutes=5) on every task (via DEFAULT_ARGS).
  - flag_reason must never be empty for flagged repositories (enforced by
    RepoScoreEngine.compute — §8.2).
  - commit_pattern_score defaults to 0.5 (neutral) when no commit data is
    available in the DAG context (commit crawl happens separately during ingest).
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timezone
from typing import Any

import structlog

import config
from ml.features.code_perplexity import CodePerplexityScorer
from ml.features.code_style import CodeStyleScorer
from ml.features.commit_pattern import CommitPatternScorer
from ml.repo_score import RepoScoreEngine
from storage.object_store import BUCKET_REPOS, ObjectStore

logger = structlog.get_logger(__name__)

_REPO_SCORES_TABLE     = "repo_scores"
_COMMIT_NEUTRAL_SCORE  = 0.5   # fallback when no commit data available in DAG


# ── MinIO factory (patchable in tests) ────────────────────────────────────────

def _make_object_store() -> ObjectStore:
    return ObjectStore(
        endpoint=config.MINIO_ENDPOINT,
        access_key=config.MINIO_ACCESS_KEY,
        secret_key=config.MINIO_SECRET_KEY,
    )


# ── Helper functions (pure, testable without Airflow) ─────────────────────────

def scan_pending_repos_in_window(
    from_ts: float,
    to_ts: float,
    _store: Any = None,
) -> list[dict[str, Any]]:
    """List repository objects crawled within [from_ts, to_ts).

    Walks the MinIO ``repos/`` bucket and returns metadata for objects whose
    ``last_modified`` timestamp falls in the given half-open interval.

    Only the first object per repo_uuid is returned (one score per repo per run).
    Source file content is NOT loaded here — that happens in score_repos_batch.

    Args:
        from_ts: Inclusive lower bound (Unix timestamp).
        to_ts: Exclusive upper bound (Unix timestamp).
        _store: Optional ObjectStore stub for test injection.

    Returns:
        List of dicts with keys: repo_uuid, object_prefix.
        Returns an empty list on MinIO error (never raises).
    """
    store = _store or _make_object_store()
    seen_repos: set[str] = set()
    pending: list[dict[str, Any]] = []

    try:
        objects = store._client.list_objects(BUCKET_REPOS, recursive=True)
        for obj in objects:
            if obj.last_modified is None:
                continue
            ts = obj.last_modified.timestamp()
            if from_ts <= ts < to_ts:
                # Object path: repos/{repo_uuid}/{file_path}
                parts = obj.object_name.split("/", 2)
                if len(parts) >= 2:
                    repo_uuid = parts[1]
                    if repo_uuid not in seen_repos:
                        seen_repos.add(repo_uuid)
                        pending.append({
                            "repo_uuid": repo_uuid,
                            "object_prefix": f"repos/{repo_uuid}/",
                        })
    except Exception as exc:
        logger.warning("minio_repo_scan_failed", error=str(exc))

    logger.info(
        "repos_scanned",
        count=len(pending),
        from_ts=from_ts,
        to_ts=to_ts,
    )
    return pending


def score_repos_batch(
    pending: list[dict[str, Any]],
    _store: Any = None,
    _engine: Any = None,
    _ppl_scorer: Any = None,
    _style_scorer: Any = None,
    _commit_scorer: Any = None,
) -> list[dict[str, Any]]:
    """Download source files and score each pending repository.

    For each repo in ``pending``:
      1. List and download all source files from MinIO ``repos/{repo_uuid}/``.
      2. Score code perplexity via CodePerplexityScorer.
      3. Score code style via CodeStyleScorer.
      4. Score commit pattern with commit_pattern_score = ``_COMMIT_NEUTRAL_SCORE``
         (neutral fallback — commit data is captured at crawl time, not available
         in DAG context without a separate store lookup).
      5. Aggregate via RepoScoreEngine.compute().

    Items that fail to download are logged and skipped without blocking the rest
    of the batch.

    Args:
        pending: List of ``{repo_uuid, object_prefix}`` dicts.
        _store: Optional ObjectStore stub for test injection.
        _engine: Optional RepoScoreEngine stub for test injection.
        _ppl_scorer: Optional CodePerplexityScorer stub for test injection.
        _style_scorer: Optional CodeStyleScorer stub for test injection.
        _commit_scorer: Optional CommitPatternScorer stub for test injection.

    Returns:
        List of serialised RepoScoreResult dicts (via dataclasses.asdict).
    """
    store          = _store or _make_object_store()
    engine         = _engine or RepoScoreEngine()
    ppl_scorer     = _ppl_scorer or CodePerplexityScorer()
    style_scorer   = _style_scorer or CodeStyleScorer()
    commit_scorer  = _commit_scorer or CommitPatternScorer()
    results: list[dict[str, Any]] = []

    for item in pending:
        repo_uuid     = item["repo_uuid"]
        object_prefix = item.get("object_prefix", f"repos/{repo_uuid}/")
        files: list[tuple[str, str]] = []

        try:
            objects = store._client.list_objects(
                BUCKET_REPOS, prefix=object_prefix, recursive=True
            )
            for obj in objects:
                try:
                    response = store._client.get_object(BUCKET_REPOS, obj.object_name)
                    content  = response.read().decode("utf-8", errors="replace")
                    response.close()
                    rel_path = obj.object_name[len(object_prefix):]
                    files.append((rel_path, content))
                except Exception as file_exc:
                    logger.warning(
                        "repo_file_download_failed",
                        repo_uuid=repo_uuid,   # UUID — no PII
                        error=str(file_exc),
                    )
        except Exception as exc:
            logger.warning(
                "repo_list_failed",
                repo_uuid=repo_uuid,           # UUID — no PII
                error=str(exc),
            )
            continue

        if not files:
            logger.warning("repo_no_files_found", repo_uuid=repo_uuid)
            continue

        file_tuples = [(fp, c) for fp, c in files]

        ppl_features    = ppl_scorer.score_repo(repo_uuid, file_tuples)
        style_features  = style_scorer.score_repo(repo_uuid, file_tuples)
        commit_features = commit_scorer.score_repo(repo_uuid, commits=[], files=file_tuples)

        score_result = engine.compute(
            repo_uuid=repo_uuid,
            code_perplexity_score=ppl_features.suspicion_score,
            commit_pattern_score=commit_features.suspicion_score,
            code_style_score=style_features.suspicion_score,
        )

        results.append(dataclasses.asdict(score_result))

    logger.info(
        "repo_batch_scored",
        total=len(pending),
        scored=len(results),
        flagged=sum(1 for r in results if r.get("flagged")),
    )
    return results


def persist_repo_scores(
    score_dicts: list[dict[str, Any]],
    delta_lake_path: str,
    _spark: Any = None,
) -> int:
    """Append repository scores to the Delta Lake repo_scores table.

    Scores are append-only — each run appends new rows identified by
    (repo_uuid, scored_at). Historical scores are preserved for audit.

    Args:
        score_dicts: Serialised RepoScoreResult dicts from score_repos_batch.
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
            .appName("TrustSignal-RepoScores")
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
            StructField("repo_uuid",      StringType(),  False),
            StructField("repo_ai_score",  DoubleType(),  False),
            StructField("suspicion_index", DoubleType(), False),
            StructField("flagged",         BooleanType(), False),
            StructField("flag_reason",     StringType(),  True),
            StructField("signals_json",    StringType(),  True),
            StructField("scored_at",       DoubleType(),  False),
        ])

        rows = [
            (
                d["repo_uuid"],
                float(d["repo_ai_score"]),
                float(d["suspicion_index"]),
                bool(d["flagged"]),
                d.get("flag_reason", ""),
                json.dumps(d.get("signals", [])),
                float(d["scored_at"]),
            )
            for d in score_dicts
        ]

        df = spark.createDataFrame(rows, schema=schema)
        table_path = f"{delta_lake_path}/{_REPO_SCORES_TABLE}"
        df.write.format("delta").mode("append").save(table_path)

        logger.info(
            "repo_scores_persisted",
            count=len(rows),
            table=_REPO_SCORES_TABLE,
        )
        return len(rows)

    except Exception as exc:
        logger.error("repo_scores_persist_failed", error=str(exc))
        return 0


def build_repo_slack_payload(stats: dict[str, Any]) -> dict[str, Any]:
    """Build a Slack Block Kit payload for the repository scoring run.

    Args:
        stats: Keys: repos_scanned, repos_scored, flagged_count,
               persisted_count, dag_run_date.

    Returns:
        Dict suitable for JSON-posting to a Slack Incoming Webhook.
    """
    scanned   = int(stats.get("repos_scanned", 0))
    scored    = int(stats.get("repos_scored", 0))
    flagged   = int(stats.get("flagged_count", 0))
    persisted = int(stats.get("persisted_count", 0))
    date      = str(stats.get("dag_run_date", ""))

    status_icon = ":shield:" if flagged > 0 else ":white_check_mark:"

    return {
        "text": f"{status_icon} TrustSignal Repo Scoring — {date}",
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"TrustSignal Repo Scoring — {date}",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Repos scanned:*\n{scanned}"},
                    {"type": "mrkdwn", "text": f"*Repos scored:*\n{scored}"},
                    {"type": "mrkdwn", "text": f"*Flagged (AI-suspected):*\n{flagged}"},
                    {"type": "mrkdwn", "text": f"*Scores persisted:*\n{persisted}"},
                ],
            },
        ],
    }


# ── Airflow task callables ─────────────────────────────────────────────────────
# These accept a standard Airflow **context dict. Importable without Airflow.

def _scan_pending_repos(**context: Any) -> dict[str, Any]:
    """Task 1: list repos crawled during the DAG data interval."""
    from_ts = context["data_interval_start"].timestamp()
    to_ts   = context["data_interval_end"].timestamp()

    pending = scan_pending_repos_in_window(from_ts, to_ts)
    return {"pending": pending, "count": len(pending)}


def _score_repos(**context: Any) -> dict[str, Any]:
    """Task 2: download source files and score each pending repo."""
    ti = context["ti"]
    result = ti.xcom_pull(task_ids="scan_pending_repos") or {}
    pending: list[dict[str, Any]] = result.get("pending", [])

    score_dicts   = score_repos_batch(pending)
    flagged_count = sum(1 for d in score_dicts if d.get("flagged"))

    return {
        "score_dicts":   score_dicts,
        "scored_count":  len(score_dicts),
        "flagged_count": flagged_count,
    }


def _persist_repo_scores(**context: Any) -> dict[str, Any]:
    """Task 3: write scores to the Delta Lake repo_scores table."""
    ti = context["ti"]
    result = ti.xcom_pull(task_ids="score_repos") or {}
    score_dicts: list[dict[str, Any]] = result.get("score_dicts", [])

    n_persisted = persist_repo_scores(score_dicts, config.DELTA_LAKE_PATH)
    return {"persisted_count": n_persisted}


def _notify_repo(**context: Any) -> None:
    """Task 4: send Slack summary of the completed repo scoring run."""
    ti = context["ti"]

    scan_r    = ti.xcom_pull(task_ids="scan_pending_repos") or {}
    score_r   = ti.xcom_pull(task_ids="score_repos") or {}
    persist_r = ti.xcom_pull(task_ids="persist_repo_scores") or {}

    stats: dict[str, Any] = {
        "repos_scanned":   scan_r.get("count", 0),
        "repos_scored":    score_r.get("scored_count", 0),
        "flagged_count":   score_r.get("flagged_count", 0),
        "persisted_count": persist_r.get("persisted_count", 0),
        "dag_run_date":    context.get("ds", ""),
    }

    webhook_url = getattr(config, "SLACK_WEBHOOK_URL", "") or ""

    if webhook_url:
        import requests as _requests
        payload = build_repo_slack_payload(stats)
        try:
            resp = _requests.Session().post(webhook_url, json=payload, timeout=10)
            resp.raise_for_status()
            logger.info("repo_slack_notification_sent")
        except Exception as exc:
            logger.error("repo_slack_notification_failed", error=str(exc))
    else:
        logger.info("repo_slack_webhook_not_configured", stats=stats)


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
        dag_id="trustsignal_repo_scoring",
        default_args=DEFAULT_ARGS,
        description=(
            "Nightly AI-detection scoring of crawled candidate GitHub repositories. "
            "Per CLAUDE.md: ML scoring runs via this DAG — never ad-hoc."
        ),
        schedule_interval="0 4 * * *",
        start_date=datetime(2026, 1, 1),
        catchup=False,
        tags=["ml", "repo", "prescreening", "trustsignal"],
    ) as dag:

        t_scan = _PythonOperator(
            task_id="scan_pending_repos",
            python_callable=_scan_pending_repos,
        )

        t_score = _PythonOperator(
            task_id="score_repos",
            python_callable=_score_repos,
        )

        t_persist = _PythonOperator(
            task_id="persist_repo_scores",
            python_callable=_persist_repo_scores,
        )

        t_notify = _PythonOperator(
            task_id="notify_repo",
            python_callable=_notify_repo,
        )

        # Linear dependency: scan → score → persist → notify
        t_scan >> t_score >> t_persist >> t_notify

except ImportError:
    # apache-airflow not installed (e.g. unit-test environment).
    # Business logic helpers and callables remain importable and testable.
    pass
