import re
from datetime import datetime, timezone

from dateutil import parser as date_parser

_QR_DATETIME_RE = re.compile(
    r"^(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2}),\s*UTC\s*([+-]\d{2}:\d{2})$"
)


def parse_qr_datetime(value: str) -> datetime:
    match = _QR_DATETIME_RE.match(value.strip())
    if match:
        day, month, year = match.group(1).split("/")
        normalized = f"{year}-{month}-{day}T{match.group(2)}{match.group(3)}"
        return date_parser.isoparse(normalized).astimezone(timezone.utc)
    return date_parser.parse(value, dayfirst=True).astimezone(timezone.utc)


def parse_transfer_date(value: str) -> datetime:
    parsed = date_parser.parse(value, dayfirst=False)
    return parsed.replace(tzinfo=timezone.utc)
