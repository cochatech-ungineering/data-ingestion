import json
import logging
from pathlib import Path
from typing import Any

import aio_pika
from pydantic import BaseModel

from app.core.config import settings
from app.services.event_archive import archive_published_event

logger = logging.getLogger(__name__)


class EventPublisher:
    def __init__(self) -> None:
        self._connection: aio_pika.RobustConnection | None = None
        self._channel: aio_pika.Channel | None = None
        self._exchange: aio_pika.Exchange | None = None

    async def connect(self) -> None:
        if self._connection and not self._connection.is_closed:
            return
        self._connection = await aio_pika.connect_robust(settings.rabbitmq_url)
        self._channel = await self._connection.channel()
        self._exchange = await self._channel.declare_exchange(
            settings.rabbitmq_exchange,
            aio_pika.ExchangeType.TOPIC,
            durable=True,
        )

    async def close(self) -> None:
        if self._connection and not self._connection.is_closed:
            await self._connection.close()
        self._connection = None
        self._channel = None
        self._exchange = None

    async def publish(self, routing_key: str, event: BaseModel) -> Path | None:
        if not settings.publish_events:
            logger.info("Publicación deshabilitada (publish_events=false): %s", routing_key)
            return None

        await self.connect()
        assert self._exchange is not None

        body = event.model_dump_json().encode("utf-8")
        message = aio_pika.Message(
            body=body,
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        )
        await self._exchange.publish(message, routing_key=routing_key)
        logger.info("Evento publicado: %s (%d bytes)", routing_key, len(body))

        if settings.archive_published_events:
            return archive_published_event(routing_key, event, body)
        return None


publisher = EventPublisher()


def chunk_events(events: list[BaseModel], chunk_size: int) -> list[list[BaseModel]]:
    if chunk_size <= 0:
        return [events]
    return [events[i : i + chunk_size] for i in range(0, len(events), chunk_size)]


def preview_model(model: BaseModel) -> dict[str, Any]:
    return json.loads(model.model_dump_json())
