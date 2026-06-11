from __future__ import annotations

import secrets

from fastapi import Header, HTTPException

from .config import settings


def require_api_token(authorization: str | None = Header(default=None)) -> None:
    if not settings.api_token:
        return
    prefix = "Bearer "
    if not authorization or not authorization.startswith(prefix):
        raise HTTPException(status_code=401, detail="Missing API token.")
    token = authorization[len(prefix) :].strip()
    if not secrets.compare_digest(token, settings.api_token):
        raise HTTPException(status_code=401, detail="Invalid API token.")
