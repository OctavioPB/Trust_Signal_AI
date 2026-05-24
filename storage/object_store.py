"""Raw audio and model artifact persistence via MinIO / S3.

Uploads PCM audio chunks under:
    raw-audio/{session_id}/{YYYYMMDD}/{chunk_seq:06d}.pcm

Model artifacts go to:
    model-artifacts/{artifact_name}   (e.g. 20260521_bg_classifier.pkl)
"""

from __future__ import annotations

import io
import re

import structlog
from minio import Minio
from minio.error import S3Error

logger = structlog.get_logger(__name__)

BUCKET_RAW_AUDIO = "raw-audio"
BUCKET_MODEL_ARTIFACTS = "model-artifacts"
BUCKET_DELTA_TABLES = "delta-tables"
BUCKET_RESUMES = "resumes"
BUCKET_REPOS = "repos"

# Strips http:// or https:// from endpoint strings so the minio client gets host:port
_PROTOCOL_RE = re.compile(r"^https?://", re.IGNORECASE)


def _strip_protocol(endpoint: str) -> str:
    return _PROTOCOL_RE.sub("", endpoint)


class ObjectStore:
    """MinIO / S3 client wrapper for TrustSignal storage operations.

    Args:
        endpoint: MinIO endpoint URL, e.g. "http://localhost:9000".
        access_key: MinIO root user / AWS access key.
        secret_key: MinIO root password / AWS secret key.
        secure: Use TLS (True in production, False for local http:// endpoints).
    """

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        secure: bool = False,
    ) -> None:
        host = _strip_protocol(endpoint)
        self._client = Minio(host, access_key=access_key, secret_key=secret_key, secure=secure)
        self._log = logger.bind(component="ObjectStore", endpoint=endpoint)

    # ── Audio chunks ──────────────────────────────────────────────────────────

    def upload_audio_chunk(
        self,
        session_id: str,
        chunk_seq: int,
        audio_bytes: bytes,
        date_str: str,
    ) -> str:
        """Upload a 500 ms PCM chunk to the raw-audio bucket.

        Args:
            session_id: UUID of the interview session (no PII).
            chunk_seq: Chunk sequence number within the session.
            audio_bytes: Raw 16-bit PCM data at 16 kHz.
            date_str: Date partition string in YYYYMMDD format.

        Returns:
            Full object path: raw-audio/{session_id}/{date_str}/{chunk_seq:06d}.pcm

        Raises:
            S3Error: On MinIO / S3 communication failure.
        """
        object_name = f"{session_id}/{date_str}/{chunk_seq:06d}.pcm"
        try:
            self._client.put_object(
                bucket_name=BUCKET_RAW_AUDIO,
                object_name=object_name,
                data=io.BytesIO(audio_bytes),
                length=len(audio_bytes),
                content_type="audio/pcm",
            )
        except S3Error as exc:
            self._log.error(
                "audio_chunk_upload_failed",
                session_id=session_id,
                chunk_seq=chunk_seq,
                error=str(exc),
            )
            raise

        full_path = f"{BUCKET_RAW_AUDIO}/{object_name}"
        self._log.debug(
            "audio_chunk_uploaded",
            session_id=session_id,
            chunk_seq=chunk_seq,
            path=full_path,
        )
        return full_path

    def list_session_chunks(self, session_id: str) -> list[str]:
        """List all stored chunk object names for a given session.

        Args:
            session_id: UUID of the interview session.

        Returns:
            Sorted list of object names within the raw-audio bucket.
        """
        objects = self._client.list_objects(
            BUCKET_RAW_AUDIO, prefix=f"{session_id}/", recursive=True
        )
        return sorted(obj.object_name for obj in objects)

    # ── Model artifacts ───────────────────────────────────────────────────────

    def upload_model_artifact(self, artifact_name: str, data: bytes) -> str:
        """Upload a versioned model artifact to model-artifacts.

        Args:
            artifact_name: Object name following YYYYMMDD_<name>.pkl convention.
            data: Serialised model bytes.

        Returns:
            Full object path: model-artifacts/{artifact_name}

        Raises:
            S3Error: On MinIO / S3 communication failure.
        """
        try:
            self._client.put_object(
                bucket_name=BUCKET_MODEL_ARTIFACTS,
                object_name=artifact_name,
                data=io.BytesIO(data),
                length=len(data),
                content_type="application/octet-stream",
            )
        except S3Error as exc:
            self._log.error("artifact_upload_failed", name=artifact_name, error=str(exc))
            raise

        full_path = f"{BUCKET_MODEL_ARTIFACTS}/{artifact_name}"
        self._log.info("artifact_uploaded", name=artifact_name, path=full_path)
        return full_path

    def delete_session_audio(self, session_id: str) -> int:
        """Delete all raw-audio objects for a session (GDPR erasure).

        Safe to call even if the session has no audio stored — returns 0.

        Args:
            session_id: UUID of the interview session (no PII).

        Returns:
            Number of objects deleted.

        Raises:
            S3Error: On MinIO / S3 communication failure.
        """
        object_names = self.list_session_chunks(session_id)
        for obj_name in object_names:
            self._client.remove_object(BUCKET_RAW_AUDIO, obj_name)
        count = len(object_names)
        self._log.info(
            "session_audio_deleted",
            session_id=session_id,   # UUID — no PII
            objects_deleted=count,
        )
        return count

    # ── Resumes ───────────────────────────────────────────────────────────────

    def upload_resume(
        self,
        candidate_uuid: str,
        timestamp_iso: str,
        file_ext: str,
        data: bytes,
    ) -> str:
        """Upload a candidate resume to the resumes bucket.

        Args:
            candidate_uuid: UUID of the candidate (no PII).
            timestamp_iso: ISO 8601 compact timestamp (e.g. "20260523T100000Z").
            file_ext: Extension without leading dot: "pdf", "docx", or "txt".
            data: Raw file bytes.

        Returns:
            Full object path: resumes/{candidate_uuid}/{timestamp_iso}.{file_ext}

        Raises:
            S3Error: On MinIO / S3 communication failure.
        """
        _CONTENT_TYPES = {
            "pdf":  "application/pdf",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "txt":  "text/plain",
        }
        object_name = f"{candidate_uuid}/{timestamp_iso}.{file_ext}"
        try:
            self._client.put_object(
                bucket_name=BUCKET_RESUMES,
                object_name=object_name,
                data=io.BytesIO(data),
                length=len(data),
                content_type=_CONTENT_TYPES.get(file_ext, "application/octet-stream"),
            )
        except S3Error as exc:
            self._log.error(
                "resume_upload_failed",
                candidate_uuid=candidate_uuid,
                error=str(exc),
            )
            raise

        full_path = f"{BUCKET_RESUMES}/{object_name}"
        self._log.info(
            "resume_uploaded",
            candidate_uuid=candidate_uuid,  # UUID — no PII
            path=full_path,
        )
        return full_path

    # ── Repository source files ───────────────────────────────────────────────

    def upload_repo_file(
        self,
        repo_uuid: str,
        file_path: str,
        content: bytes,
    ) -> str:
        """Upload a crawled source file to the repos bucket.

        Args:
            repo_uuid: UUID of the repository (no PII).
            file_path: Relative path within the repository (e.g. ``src/main.py``).
            content: Raw UTF-8 encoded file content.

        Returns:
            Full object path: repos/{repo_uuid}/{file_path}

        Raises:
            S3Error: On MinIO / S3 communication failure.
        """
        safe_path = file_path.lstrip("/").replace("\\", "/")
        object_name = f"{repo_uuid}/{safe_path}"
        try:
            self._client.put_object(
                bucket_name=BUCKET_REPOS,
                object_name=object_name,
                data=io.BytesIO(content),
                length=len(content),
                content_type="text/plain; charset=utf-8",
            )
        except S3Error as exc:
            self._log.error(
                "repo_file_upload_failed",
                repo_uuid=repo_uuid,   # UUID — no PII
                error=str(exc),
            )
            raise

        full_path = f"{BUCKET_REPOS}/{object_name}"
        self._log.debug(
            "repo_file_uploaded",
            repo_uuid=repo_uuid,   # UUID — no PII
            path=full_path,
            size_bytes=len(content),
        )
        return full_path

    def download_model_artifact(self, artifact_name: str) -> bytes:
        """Download a model artifact by name.

        Args:
            artifact_name: Object name within the model-artifacts bucket.

        Returns:
            Raw bytes of the artifact.

        Raises:
            S3Error: If the artifact does not exist or cannot be retrieved.
        """
        response = self._client.get_object(BUCKET_MODEL_ARTIFACTS, artifact_name)
        try:
            data = response.read()
        finally:
            response.close()
            response.release_conn()

        self._log.info("artifact_downloaded", name=artifact_name, size_bytes=len(data))
        return data
