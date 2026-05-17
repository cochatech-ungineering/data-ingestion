import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from botocore.exceptions import ClientError

from app.core.config import settings
from app.schemas.contracts import FileType
from app.storage.aws_session import client_kwargs, get_session

logger = logging.getLogger(__name__)


class RawFileStorage:
    """Almacenamiento de archivos crudos en Amazon S3."""

    @property
    def bucket(self) -> str:
        return settings.s3_bucket

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

    async def ensure_bucket(self) -> None:
        session = get_session()
        async with session.client("s3", **client_kwargs()) as s3:
            try:
                await s3.head_bucket(Bucket=self.bucket)
                return
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                if code not in {"404", "NoSuchBucket", "403"}:
                    raise

            params: dict = {"Bucket": self.bucket}
            if settings.aws_region != "us-east-1":
                params["CreateBucketConfiguration"] = {
                    "LocationConstraint": settings.aws_region
                }
            await s3.create_bucket(**params)
            logger.info("Bucket S3 creado: %s", self.bucket)

    async def upload_bytes(
        self,
        *,
        object_key: str,
        data: bytes,
        content_type: str,
    ) -> None:
        await self.ensure_bucket()
        session = get_session()
        async with session.client("s3", **client_kwargs()) as s3:
            await s3.put_object(
                Bucket=self.bucket,
                Key=object_key,
                Body=data,
                ContentType=content_type,
            )

    async def download_to_path(self, *, object_key: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        session = get_session()
        async with session.client("s3", **client_kwargs()) as s3:
            try:
                response = await s3.get_object(Bucket=self.bucket, Key=object_key)
                body = await response["Body"].read()
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                if code in {"NoSuchKey", "404"}:
                    raise FileNotFoundError(
                        f"Objeto no encontrado en S3: s3://{self.bucket}/{object_key}"
                    ) from exc
                raise
        destination.write_bytes(body)
        return destination

    async def check_bucket(self) -> bool:
        session = get_session()
        async with session.client("s3", **client_kwargs()) as s3:
            try:
                await s3.head_bucket(Bucket=self.bucket)
                return True
            except ClientError:
                return False


raw_file_storage = RawFileStorage()
