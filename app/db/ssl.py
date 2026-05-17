import ssl
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from app.core.config import settings

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _resolve_ca_path() -> Path | None:
    if not settings.database_ssl_ca:
        return None
    path = Path(settings.database_ssl_ca)
    if not path.is_absolute():
        path = _PROJECT_ROOT / path
    return path if path.is_file() else None


def database_dsn_and_ssl() -> tuple[str, ssl.SSLContext | bool | None]:
    """Devuelve DSN sin query ssl y contexto SSL para asyncpg (p. ej. RDS)."""
    parsed = urlparse(settings.database_url)
    query = parse_qs(parsed.query)
    sslmode = query.get("sslmode", [None])[0]
    host = parsed.hostname or ""

    if "sslmode" in query:
        del query["sslmode"]
    clean_query = urlencode({k: v[0] for k, v in query.items()}, doseq=False)
    dsn = urlunparse(parsed._replace(query=clean_query))

    needs_ssl = sslmode in ("require", "verify-ca", "verify-full") or ".rds.amazonaws.com" in host
    if not needs_ssl:
        return dsn, None

    ca_path = _resolve_ca_path()
    if ca_path is not None:
        return dsn, ssl.create_default_context(cafile=str(ca_path))

    if sslmode == "require":
        return dsn, True

    raise RuntimeError(
        "Conexión RDS requiere certificado CA. Descarga infrastructure/rds-ca-global.pem "
        "o define DATABASE_SSL_CA."
    )
