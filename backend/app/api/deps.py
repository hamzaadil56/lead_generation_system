import secrets
from typing import Iterator

from fastapi import Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal


def get_db() -> Iterator[Session]:
    """One session per request, always closed.

    Overridden in tests so every router shares the rolled-back fixture
    session.
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def require_api_key(x_api_key: str | None = Header(None)) -> None:
    """Single-user auth (spec section 9): Next.js holds the key server-side.

    `compare_digest` rather than `==` so the check is not timing-variable.
    A missing configured key fails closed -- an unset API_KEY must not mean
    "no auth required". Both sides are encoded to bytes before comparing:
    `compare_digest` rejects `str` operands containing non-ASCII characters
    with a `TypeError`, and a malformed header must fail closed as a 401,
    not surface as an unhandled 500 on the auth boundary.
    """
    configured = get_settings().api_key
    if not configured or not x_api_key or not secrets.compare_digest(
            x_api_key.encode("utf-8"), configured.encode("utf-8")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="invalid or missing API key")
