# Análisis: ¿Usar Polars en la limpieza de CSV?

## Qué hace este servicio con los datos

1. Leer CSV de pagos QR (~5.300 filas) o transferencias (~140 filas).
2. Seleccionar columnas útiles, filtrar filas inválidas, castear tipos, deduplicar.
3. Parsear fechas con formato no estándar (`15/04/2025 09:01:55, UTC -04:00`).
4. Validar con Pydantic y serializar a JSON para el event bus.

No hay joins complejos, modelos de ML ni ventanas temporales avanzadas en esta capa.

## Polars vs alternativas

| Aspecto | Polars | pandas | csv + stdlib |
|---------|--------|--------|----------------|
| Velocidad en ~5k filas | Excelente | Suficiente | Suficiente |
| API expresiva (filter, cast, unique) | Sí, lazy opcional | Sí | Verbosa |
| Memoria | Muy eficiente (Arrow) | Mayor overhead | Mínima |
| Dependencia | ~15 MB wheel | ~40 MB+ stack | Ninguna |
| Curva de aprendizaje | Media | Media-alta | Baja |

## Conclusión

**Sí conviene Polars aquí**, aunque el volumen actual no lo exija por rendimiento.

Razones:

1. **Pipeline declarativo legible**: `select → rename → filter → cast → unique` documenta las reglas de limpieza en pocas líneas y es fácil de extender cuando el CSV crezca a cientos de miles de filas.
2. **Tipado estricto temprano**: los casts a `Float64` / `Int64` detectan basura en el CSV antes de llegar al motor de cashback.
3. **Escalabilidad sin reescribir**: si el hackatón pasa a reportes de millones de filas, el mismo código Polars escala con lazy scan (`scan_csv`) sin cambiar la API.
4. **Costo bajo**: una dependencia, sin el ecosistema pesado de pandas.

Cuándo **no** usar Polars: si el equipo prohibiera dependencias nativas o el despliegue fuera en un entorno ultra-restringido; en ese caso `csv.DictReader` + validación Pydantic alcanzaría para el volumen actual.

## Validación previa (estado Completed)

Antes de normalizar montos o publicar eventos, el pipeline ejecuta `validate_qr_completed_status`:

1. Lee la columna `Estado` del CSV crudo.
2. Cuenta filas por estado (`status_breakdown`).
3. Filtra solo `Completed` (case-insensitive).
4. Rechaza la ingesta si no hay ninguna fila `Completed`, o si `strict_status=true` y quedan filas excluidas.

La respuesta de la API incluye el bloque `validation` con totales y desglose.

## Columnas descartadas del CSV QR

| Columna original | Motivo |
|------------------|--------|
| Side Cliente | Constante `Sell` en el dataset |
| Moneda | Constante `BOB` |
| OMS | Metadato operativo (`Banexcoin Bolivia`) |
| Fecha de actualización | No necesaria para cálculo mensual de consumo |

## Columnas conservadas (contrato)

`quote_number`, `transaction_id`, `user_alias`, `account_number`, `amount_bob`, `amount_usdt`, `exchange_rate`, `commission_usdt`, `created_at`, `service_code`, `status`.
