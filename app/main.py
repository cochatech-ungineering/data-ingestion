import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes.ingest import router as ingest_router
from app.core.config import settings
from app.services.publisher import publisher

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.publish_events:
        try:
            await publisher.connect()
        except Exception:
            logging.getLogger(__name__).warning(
                "RabbitMQ no disponible al iniciar; la API seguirá funcionando con publish=false."
            )
    yield
    await publisher.close()


app = FastAPI(
    title="Data Ingestion API",
    description="Limpieza de reportes QR y publicación de eventos para el motor de cashback.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(ingest_router)


@app.get("/health")
def health():
    return {"status": "ok", "service": settings.app_name}
