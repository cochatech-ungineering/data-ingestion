# Persistencia de datos: qué guardar y dónde

Este servicio usa **dos almacenes**:

| Almacén | Contenido |
|---------|-----------|
| **MinIO** | Archivo crudo subido por el usuario (CSV, XLS, XLSX, JSON, TXT) |
| **PostgreSQL** | Job de ingesta, hash de contenido (anti-duplicados), estado del pipeline y metadatos para reintentos |

Los estados del job en Postgres son: `received` → `stored` → `converting` → `processing` → `publishing` → `completed` (o `failed` con `error_stage` y `error_message`).

Reintento: `POST /api/v1/ingest/jobs/{id}/retry` descarga el objeto desde MinIO usando `minio_object_key` y vuelve a ejecutar el pipeline.

## Responsabilidades por capa

| Capa | Responsabilidad | Persistencia |
|------|-----------------|--------------|
| Ingesta (este repo) | Crudo en MinIO + estado en Postgres + eventos | MinIO + PostgreSQL |
| Motor de cashback | Agregación mensual, niveles, reintegros | PostgreSQL (Supabase) |
| Reportes operativos | Export BanexTransfer | Object storage (S3/MinIO) o filesystem |

## Qué debe guardar el motor de cashback (downstream)

### Tabla `qr_transactions` (hechos)

- `report_id` (UUID de la ingesta)
- `transaction_id` (único)
- `user_alias`, `account_number`
- `amount_bob`, `amount_usdt`, `exchange_rate`, `commission_usdt`
- `created_at`
- Índice único: `(transaction_id)` para idempotencia

### Tabla `monthly_user_consumption` (agregado)

- `user_alias`, `year_month`
- `total_bob`, `total_usdt`
- `tier_level`, `cashback_pct`
- `cashback_usdt`, `cashback_bob`
- Índice único: `(user_alias, year_month)`

### Tabla `ingestion_runs` (auditoría)

- `report_id`, `source_file`, `file_type`
- `total_records`, `period_start`, `period_end`
- `status`, `processed_at`

## CSV crudo (opcional pero recomendado)

Guardar el archivo original subido permite:

- Reprocesar un mes si cambian las reglas de niveles.
- Auditar discrepancias con operaciones.

**Recomendación**: bucket privado con ruta `ingestion/{year}/{month}/{report_id}.csv` y retención de 24 meses.

## Por qué no guardar todo en el mensaje del bus

Los eventos llevan lotes para procesamiento en tiempo casi real. La **fuente de verdad** debe ser la base del motor de cashback, no SQS (retención limitada).

## Supabase / Postgres

Para el hackatón, Postgres (vía Supabase) es adecuado:

- SQL para reportes (`SUM`, `GROUP BY` por usuario/mes).
- RLS si más adelante hay panel por operador.
- Funciones o jobs para exportar CSV de BanexTransfer.

No se recomienda almacenar solo en JSON files a largo plazo: dificulta consultas concurrentes e idempotencia.

## Idempotencia

El consumidor debe usar `transaction_id` (QR) o `transfer_number` (transferencias) como clave natural:

```sql
INSERT INTO qr_transactions (...)
ON CONFLICT (transaction_id) DO NOTHING;
```

Así, re-publicar el mismo `report_id` no duplica consumo.
