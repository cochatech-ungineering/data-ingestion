from typing import Any

import aioboto3

from app.core.config import settings


def get_session() -> aioboto3.Session:
    if settings.aws_profile:
        return aioboto3.Session(profile_name=settings.aws_profile)
    return aioboto3.Session()


def client_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {"region_name": settings.aws_region}
    if settings.aws_endpoint_url:
        kwargs["endpoint_url"] = settings.aws_endpoint_url
    return kwargs
