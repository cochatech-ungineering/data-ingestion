"""Utilidades para consumidores SQS que reciben mensajes envueltos por SNS."""

import json
from typing import Any


def unwrap_sns_sqs_body(sqs_body: str) -> tuple[str, dict[str, Any]]:
    """
    Extrae el payload de ingesta desde el cuerpo de un mensaje SQS originado por SNS.

    Returns:
        (event_type, payload_dict) — event_type equivale al routing_key de RabbitMQ.
    """
    envelope = json.loads(sqs_body)
    if envelope.get("Type") != "Notification":
        raise ValueError("Mensaje SQS sin envoltorio SNS Notification")

    inner = json.loads(envelope["Message"])
    attrs = envelope.get("MessageAttributes") or {}
    event_type_attr = attrs.get("event_type") or {}
    event_type = event_type_attr.get("Value") or event_type_attr.get("StringValue") or ""

    if not event_type and isinstance(inner, dict):
        event_type = inner.get("event_type", "")

    return event_type, inner
