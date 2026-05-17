import logging
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from uuid import UUID

from minio import Minio
from minio.error import S3Error

from app.core.config import settings
from app.schemas.contracts import FileType

logger = logging.getLogger(__name__)


class RawFileStorage:
    def __init__(self) -> None:
        self._client: Minio | None = None

    @property
    def client(self) -> Minio:
        if self._client is None:
            self._client = Minio(
                settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=settings.minio_secure,
                region=settings.minio_region,
            )
        return self._client

    @property
    def bucket(self) -> str:
        return settings.minio_bucket

    def ensure_bucket(self) -> None:
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)
            logger.info("Bucket MinIO creado: %s", self.bucket)

    def build_object_key(
        self,
        *,
        job_id: UUID,
        file_type: FileType,
        original_filename: str,
    ) -> str:
        now = datetime.now(timezone.utc)
        safe_name = Path(original_filename).name.replace(" ", "_")
        return (
            f"raw/{file_type.value}/{now.year:04d}/{now.month:02d}/"
            f"{job_id}/{safe_name}"
        )

    def upload_bytes(
        self,
        *,
        object_key: str,
        data: bytes,
        content_type: str,
    ) -> None:
        self.ensure_bucket()
        self.client.put_object(
            self.bucket,
            object_key,
            BytesIO(data),
            length=len(data),
            content_type=content_type,
        )

    def download_to_path(self, *, object_key: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            response = self.client.get_object(self.bucket, object_key)
        except S3Error as exc:
            raise FileNotFoundError(f"Objeto no encontrado en MinIO: {object_key}") from exc
        try:
            destination.write_bytes(response.read())
        finally:
            response.close()
            response.release_conn()
        return destination


raw_file_storage = RawFileStorage()
