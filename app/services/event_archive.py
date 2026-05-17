import json
import logging
from pathlib import Path
from pydantic import BaseModel

from app.core.config import settings

logger = logging.getLogger(__name__)


def _report_id_from_event(event: BaseModel) -> str:
    report_id = getattr(event, "report_id", None)
    if report_id is None:
        return "unknown"
    return str(report_id)


def _filename_for(routing_key: str, event: BaseModel) -> str:
    safe_key = routing_key.replace(".", "-")
    payload = event.model_dump()
    batch_index = payload.get("batch_index")
    if batch_index is not None:
        batch_count = payload.get("batch_count", "?")
        return f"{safe_key}_batch-{int(batch_index):04d}-of-{batch_count}.json"
    return f"{safe_key}.json"


def archive_published_event(routing_key: str, event: BaseModel, payload: bytes) -> Path:
    report_dir = Path(settings.events_output_dir) / _report_id_from_event(event)
    report_dir.mkdir(parents=True, exist_ok=True)

    destination = report_dir / _filename_for(routing_key, event)
    parsed = json.loads(payload.decode("utf-8"))
    destination.write_text(
        json.dumps(parsed, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    logger.info("Evento archivado en %s", destination)
    return destination
