import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes.ingest import router as ingest_router
from app.api.routes.jobs import router as jobs_router
from app.core.config import settings
from app.db.connection import close_db, init_db
from app.services.publisher import publisher
from app.storage.minio_storage import raw_file_storage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    try:
        raw_file_storage.ensure_bucket()
    except Exception:
        logger.warning("MinIO no disponible al iniciar; las ingestas fallarán hasta que esté activo.")

    if settings.publish_events:
        try:
            await publisher.connect()
        except Exception:
            logger.warning(
                "SNS no disponible al iniciar; revisa SNS_TOPIC_ARN y AWS_PROFILE. "
                "La API seguirá con publish=false o fallará al publicar."
            )
    yield
    await publisher.close()
    await close_db()


app = FastAPI(
    title="Data Ingestion API",
    description=(
        "Ingesta de reportes QR/transferencias: almacenamiento crudo en MinIO, "
        "seguimiento de estado en PostgreSQL y publicación de eventos vía SNS."
    ),
    version="1.1.0",
    lifespan=lifespan,
)

app.include_router(ingest_router)
app.include_router(jobs_router)


@app.get("/health")
async def health():
    db_ok = False
    minio_ok = False
    try:
        from app.db.connection import get_pool

        await get_pool().fetchval("SELECT 1")
        db_ok = True
    except Exception:
        pass
    try:
        minio_ok = raw_file_storage.client.bucket_exists(raw_file_storage.bucket)
    except Exception:
        pass
    sns_ok = False
    if settings.sns_topic_arn and settings.publish_events:
        try:
            await publisher.connect()
            sns_ok = True
        except Exception:
            pass
    return {
        "status": "ok" if db_ok and minio_ok and (sns_ok or not settings.publish_events) else "degraded",
        "service": settings.app_name,
        "postgres": db_ok,
        "minio": minio_ok,
        "sns": sns_ok if settings.publish_events else None,
    }
