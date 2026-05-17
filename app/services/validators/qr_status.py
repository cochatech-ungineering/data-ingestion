import polars as pl

from app.schemas.contracts import QrStatusValidationReport

STATUS_COLUMN = "Estado"
REQUIRED_STATUS = "completed"


class QrStatusValidationError(ValueError):
    """El CSV no cumple la precondición de estado Completed para cashback."""

    def __init__(self, report: QrStatusValidationReport):
        self.report = report
        if report.completed_rows == 0:
            message = (
                "No se encontraron transacciones con estado 'Completed'. "
                "Solo las transacciones completadas son válidas para el análisis de cashback."
            )
        else:
            message = (
                f"Se excluyeron {report.excluded_rows} filas con estado distinto de 'Completed'. "
                f"Estados encontrados: {report.status_breakdown}"
            )
        super().__init__(message)


def validate_qr_completed_status(df: pl.DataFrame, *, strict: bool = True) -> tuple[pl.DataFrame, QrStatusValidationReport]:
    """
    Primera fase del pipeline QR: validar y filtrar por estado Completed.

    Debe ejecutarse antes de normalizar montos, deduplicar o publicar eventos.
    """
    if STATUS_COLUMN not in df.columns:
        raise ValueError(f"Columna requerida ausente en CSV QR: '{STATUS_COLUMN}'")

    normalized_status = (
        pl.col(STATUS_COLUMN)
        .cast(pl.Utf8)
        .str.strip_chars()
        .str.to_lowercase()
    )

    analyzed = df.with_columns(normalized_status.alias("_status_normalized"))
    status_breakdown = (
        analyzed.group_by("_status_normalized")
        .len()
        .sort("_status_normalized")
        .rename({"_status_normalized": "status", "len": "count"})
    )

    breakdown: dict[str, int] = {}
    for row in status_breakdown.iter_rows(named=True):
        label = row["status"] if row["status"] else "(vacío)"
        breakdown[label] = row["count"]

    total_rows = analyzed.height
    completed_df = analyzed.filter(pl.col("_status_normalized") == REQUIRED_STATUS).drop("_status_normalized")
    completed_rows = completed_df.height
    excluded_rows = total_rows - completed_rows

    report = QrStatusValidationReport(
        total_rows=total_rows,
        completed_rows=completed_rows,
        excluded_rows=excluded_rows,
        status_breakdown=breakdown,
        required_status="Completed",
        passed=completed_rows > 0 and (not strict or excluded_rows == 0),
    )

    if completed_rows == 0:
        raise QrStatusValidationError(report)

    if strict and excluded_rows > 0:
        raise QrStatusValidationError(report)

    return completed_df, report
