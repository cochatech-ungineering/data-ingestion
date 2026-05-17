# Persistencia de datos: S3 + RDS (AWS)

| Capa | Almacén | Contenido |
|------|---------|-----------|
| **Ingesta (este repo)** | **S3** | Archivo crudo (CSV, XLS, JSON, TXT) |
| **Ingesta (este repo)** | **RDS PostgreSQL** | Jobs, estados, hash anti-duplicados |
| **Motor de cashback** | RDS propio | Transacciones, agregados mensuales |
| **Bus de eventos** | SNS + SQS | Eventos JSON (no fuente de verdad) |

## Provisionar en AWS

```bash
export AWS_PROFILE=cochatech-dev
./scripts/provision_aws_data.sh   # S3 + RDS + migración
./scripts/provision_sns_sqs.sh    # SNS + SQS (si aún no)
```

Copiar `infrastructure/aws-data.env` → `.env` (`S3_BUCKET`, `DATABASE_URL`).

## Reintento

`POST /api/v1/ingest/jobs/{id}/retry` descarga el objeto desde S3 (`minio_object_key` en DB) y reprocesa.

## Idempotencia

Hash SHA-256 del archivo en `ingestion_jobs.content_hash` (único).
