import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes.ingest import router as ingest_router
from app.api.routes.jobs import router as jobs_router
from app.core.config import settings
from app.db.connection import close_db, init_db
from app.services.publisher import publisher
from app.storage.s3_storage import raw_file_storage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not settings.database_url:
        raise RuntimeError(
            "DATABASE_URL no configurado. Ejecuta scripts/provision_aws_data.sh "
            "y copia las variables a .env"
        )
    await init_db()
    try:
        await raw_file_storage.ensure_bucket()
    except Exception:
        logger.warning(
            "S3 no disponible al iniciar; revisa S3_BUCKET y credenciales AWS."
        )

    if settings.publish_events:
        try:
            await publisher.connect()
        except Exception:
            logger.warning(
                "SNS no disponible al iniciar; revisa SNS_TOPIC_ARN y AWS_PROFILE."
            )
    yield
    await publisher.close()
    await close_db()


app = FastAPI(
    title="Data Ingestion API",
    description=(
        "Ingesta de reportes QR/transferencias: archivos crudos en S3, "
        "estado en RDS PostgreSQL y eventos vía SNS."
    ),
    version="1.2.0",
    lifespan=lifespan,
)

app.include_router(ingest_router)
app.include_router(jobs_router)


@app.get("/health")
async def health():
    db_ok = False
    s3_ok = False
    try:
        from app.db.connection import get_pool

        await get_pool().fetchval("SELECT 1")
        db_ok = True
    except Exception:
        pass
    try:
        s3_ok = await raw_file_storage.check_bucket()
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
        "status": "ok" if db_ok and s3_ok and (sns_ok or not settings.publish_events) else "degraded",
        "service": settings.app_name,
        "postgres": db_ok,
        "s3": s3_ok,
        "sns": sns_ok if settings.publish_events else None,
    }
