import json
import logging
from pathlib import Path
from typing import Any

import aioboto3
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel

from app.core.config import settings
from app.services.event_archive import archive_published_event

logger = logging.getLogger(__name__)

# Atributo SNS equivalente a routing_key en RabbitMQ topic exchange
EVENT_TYPE_ATTRIBUTE = "event_type"


class EventPublisher:
    def __init__(self) -> None:
        self._session = (
            aioboto3.Session(profile_name=settings.aws_profile)
            if settings.aws_profile
            else aioboto3.Session()
        )
        self._client_cm = None
        self._sns = None

    def _client_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"region_name": settings.aws_region}
        if settings.aws_endpoint_url:
            kwargs["endpoint_url"] = settings.aws_endpoint_url
        return kwargs

    async def connect(self) -> None:
        if self._sns is not None:
            return
        if not settings.sns_topic_arn:
            raise ValueError(
                "SNS_TOPIC_ARN no configurado. Ejecuta scripts/provision_sns_sqs.sh "
                "y copia las variables a .env"
            )
        self._client_cm = self._session.client("sns", **self._client_kwargs())
        self._sns = await self._client_cm.__aenter__()
        await self._sns.get_topic_attributes(TopicArn=settings.sns_topic_arn)
        logger.info("SNS conectado: %s", settings.sns_topic_arn)

    async def close(self) -> None:
        if self._client_cm is not None:
            await self._client_cm.__aexit__(None, None, None)
        self._client_cm = None
        self._sns = None

    async def publish(self, routing_key: str, event: BaseModel) -> Path | None:
        if not settings.publish_events:
            logger.info("Publicación deshabilitada (publish_events=false): %s", routing_key)
            return None

        await self.connect()
        assert self._sns is not None

        body = event.model_dump_json()
        try:
            response = await self._sns.publish(
                TopicArn=settings.sns_topic_arn,
                Message=body,
                MessageAttributes={
                    EVENT_TYPE_ATTRIBUTE: {
                        "DataType": "String",
                        "StringValue": routing_key,
                    }
                },
            )
        except (ClientError, BotoCoreError) as exc:
            raise RuntimeError(f"Error publicando en SNS ({routing_key}): {exc}") from exc

        message_id = response.get("MessageId", "?")
        logger.info(
            "Evento publicado en SNS: %s (%d bytes, MessageId=%s)",
            routing_key,
            len(body.encode()),
            message_id,
        )

        if settings.archive_published_events:
            return archive_published_event(routing_key, event, body.encode())
        return None


publisher = EventPublisher()


def chunk_events(events: list[BaseModel], chunk_size: int) -> list[list[BaseModel]]:
    if chunk_size <= 0:
        return [events]
    return [events[i : i + chunk_size] for i in range(0, len(events), chunk_size)]


def preview_model(model: BaseModel) -> dict[str, Any]:
    return json.loads(model.model_dump_json())
