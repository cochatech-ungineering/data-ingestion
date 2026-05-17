# Event bus: Amazon SNS + SQS (AWS)

## Flujo

```
CSV → API de ingesta → limpieza (Polars) → SNS topic → SQS (por consumidor) → Motor de cashback
```

Este servicio es **productor único**. Publica en un **topic SNS** en AWS; cada consumidor tiene su **cola SQS** con filtro por tipo de evento.

No hay infra local: datos en **S3 + RDS**, eventos en **SNS/SQS** (AWS).

## Mapeo desde RabbitMQ

| RabbitMQ (antes) | AWS (ahora) |
|------------------|-------------|
| Exchange `cashback.ingestion` (topic) | SNS topic `cashback-ingestion` |
| `routing_key` al publicar | Atributo de mensaje SNS `event_type` |
| Cola `cashback.qr.processor` + binding `qr.*` | SQS `cashback-qr-processor` + filter policy prefix `qr.` |
| Cola `cashback.transfers.processor` + `transfers.*` | SQS `cashback-transfers-processor` + prefix `transfers.` |

### event_type (contrato JSON sin cambios)

| event_type | Descripción |
|------------|-------------|
| `qr.transactions.batch` | Lote de transacciones QR limpias (~500 por mensaje) |
| `qr.ingestion.completed` | Resumen del reporte QR procesado |
| `transfers.ingestion.completed` | Transferencias USDT limpias |

## Provisionar en AWS

```bash
export AWS_PROFILE=cochatech-dev   # o tu perfil con aws login
unset AWS_ENDPOINT_URL
./scripts/provision_sns_sqs.sh
# Copiar variables de infrastructure/sns-sqs.env a .env
```

## Consumidor (motor de cashback)

Los mensajes en SQS llegan **envueltos por SNS**. Usar `app.services.sqs_envelope.unwrap_sns_sqs_body`:

```python
from app.services.sqs_envelope import unwrap_sns_sqs_body

event_type, payload = unwrap_sns_sqs_body(sqs_message["Body"])
```

Colas en cuenta `545349726305` (us-east-1):

- `cashback-qr-processor`
- `cashback-transfers-processor`

Cada cola tiene DLQ (`*-dlq`) tras 5 reintentos.

## Variables de entorno (productor)

| Variable | Descripción |
|----------|-------------|
| `SNS_TOPIC_ARN` | ARN del topic (requerido) |
| `AWS_REGION` | Región (default `us-east-1`) |
| `AWS_PROFILE` | Perfil CLI (`cochatech-dev`) |
| `PUBLISH_EVENTS` | `false` desactiva publicación |

## Límites

- Tamaño máximo SNS/SQS: **256 KB** por mensaje. Reducir `EVENT_CHUNK_SIZE` si hace falta.
