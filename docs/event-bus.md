# Análisis: RabbitMQ vs Kafka para ingesta de cashback

## Contexto del flujo

```
CSV (QR / Transfers) → API de ingesta → limpieza (Polars) → eventos JSON → Event Bus → Motor de cashback
```

Este servicio es **productor único** de eventos de ingesta. El motor de cashback (y posibles workers de reportes BanexTransfer) son **consumidores**.

## Comparativa

| Criterio | RabbitMQ | Kafka |
|----------|----------|-------|
| Complejidad operativa | Baja (1 contenedor + UI) | Media-alta (ZK/KRaft + brokers) |
| Modelo mental | Colas / routing por clave | Log append-only particionado |
| Volumen actual (~5k QR/mes) | Sobrado | Sobrado |
| Escalado a millones de txs/mes | Requiere sharding manual o múltiples colas | Particiones nativas |
| Reprocesamiento histórico | Requiere dead-letter o re-publicar | Replay por offset |
| Orden por usuario | Cola dedicada o consumer único | Misma partición = mismo `user_alias` |
| Latencia end-to-end | Muy baja | Baja-media |
| Integración Python | `aio-pika` maduro | `aiokafka` / `confluent-kafka` |

## Recomendación para este proyecto

**Usar RabbitMQ como bus por defecto.**

Motivos concretos:

1. **Carga esperada del hackatón**: ~5.300 transacciones QR y ~140 transferencias. No se necesita un log distribuido de alta throughput.
2. **Patrón de trabajo**: publicar lotes (`qr.transactions.batch`) y un evento de cierre (`qr.ingestion.completed`) encaja con exchanges tipo `topic`.
3. **Menos fricción**: un solo servicio en `docker-compose.yml` (RabbitMQ **4.1**), consola en `http://localhost:15672` (guest/guest).
4. **Auditoría local**: cada mensaje publicado con éxito se guarda en `events/published/{report_id}/` como JSON legible.
4. **Menos errores humanos**: configuración mínima para el equipo que solo sube CSV y espera que el motor procese.

Kafka queda como **perfil opcional** (`docker compose --profile kafka up`) si más adelante se requiere:

- Auditoría inmutable de todos los eventos de ingesta.
- Múltiples consumidores independientes (cashback, BI, alertas) leyendo el mismo stream sin competir.
- Reprocesar un mes completo cambiando solo el offset del consumer.

## Diseño implementado (RabbitMQ)

- **Exchange**: `cashback.ingestion` (tipo `topic`, durable)
- **Routing keys**:
  - `qr.transactions.batch` — lote de transacciones limpias (default 500 por mensaje)
  - `qr.ingestion.completed` — resumen del reporte procesado
  - `transfers.ingestion.completed` — transferencias USDT limpias (referencia para pagos masivos)

### Suscripción sugerida en el motor de cashback

```
exchange: cashback.ingestion
queue: cashback.qr.processor
binding: qr.*
```

```
exchange: cashback.ingestion
queue: cashback.transfers.processor
binding: transfers.*
```

## Migración futura a Kafka

Si el volumen crece, mapear:

| RabbitMQ | Kafka |
|----------|-------|
| `qr.transactions.batch` | topic `cashback.qr.transactions` |
| `qr.ingestion.completed` | topic `cashback.qr.ingestion.completed` |
| `report_id` en payload | key de partición opcional (`user_alias` para orden por usuario) |

Mantener el **mismo JSON** (data contract v1) para no reescribir el motor.
