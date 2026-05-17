import json
from enum import Enum
from pathlib import Path
from tempfile import NamedTemporaryFile

import polars as pl

ALLOWED_EXTENSIONS = frozenset({".csv", ".xls", ".xlsx", ".json", ".txt"})


class UploadMediaType(str, Enum):
    CSV = "text/csv"
    XLS = "application/vnd.ms-excel"
    XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    JSON = "application/json"
    TXT = "text/plain"
    OCTET = "application/octet-stream"


EXTENSION_MEDIA: dict[str, UploadMediaType] = {
    ".csv": UploadMediaType.CSV,
    ".xls": UploadMediaType.XLS,
    ".xlsx": UploadMediaType.XLSX,
    ".json": UploadMediaType.JSON,
    ".txt": UploadMediaType.TXT,
}


def validate_upload_filename(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise ValueError(f"Tipo de archivo no permitido. Extensiones válidas: {allowed}")
    return suffix


def media_type_for_extension(suffix: str) -> str:
    return EXTENSION_MEDIA.get(suffix, UploadMediaType.OCTET).value


def _write_temp_csv(df: pl.DataFrame) -> Path:
    with NamedTemporaryFile(delete=False, suffix=".csv", mode="w", encoding="utf-8") as tmp:
        df.write_csv(tmp.name)
        return Path(tmp.name)


def _read_delimited(path: Path) -> pl.DataFrame:
    try:
        return pl.read_csv(
            path,
            infer_schema_length=10_000,
            null_values=["", "NA", "N/A"],
        )
    except Exception:
        return pl.read_csv(
            path,
            separator="\t",
            infer_schema_length=10_000,
            null_values=["", "NA", "N/A"],
        )


def _read_excel(path: Path) -> pl.DataFrame:
    try:
        return pl.read_excel(path)
    except Exception as exc:
        raise ValueError(f"No se pudo leer el archivo Excel: {exc}") from exc


def _read_json(path: Path) -> pl.DataFrame:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        if not payload:
            raise ValueError("El JSON está vacío.")
        if not all(isinstance(item, dict) for item in payload):
            raise ValueError("Se espera un arreglo JSON de objetos.")
        return pl.DataFrame(payload)
    if isinstance(payload, dict):
        for key in ("data", "records", "items", "transactions", "transfers"):
            nested = payload.get(key)
            if isinstance(nested, list) and nested and all(isinstance(item, dict) for item in nested):
                return pl.DataFrame(nested)
    raise ValueError(
        "Formato JSON no soportado. Use un arreglo de objetos o un objeto con clave "
        "data/records/items/transactions/transfers."
    )


def materialize_as_csv(source: Path) -> tuple[Path, bool]:
    """
    Devuelve (ruta_csv, debe_borrarse).
    Si el archivo ya es CSV utilizable, debe_borrarse=False.
    """
    suffix = source.suffix.lower()
    if suffix == ".csv":
        return source, False
    if suffix == ".txt":
        df = _read_delimited(source)
        return _write_temp_csv(df), True
    if suffix in {".xls", ".xlsx"}:
        df = _read_excel(source)
        return _write_temp_csv(df), True
    if suffix == ".json":
        df = _read_json(source)
        return _write_temp_csv(df), True
    raise ValueError(f"Extensión no soportada: {suffix}")
