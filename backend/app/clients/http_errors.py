"""Translate provider SDK exceptions into the project's error taxonomy.

Before this module existed, `app/core/errors.py` was defined and tested but
never raised anywhere in `app/`: the tenacity retry on
`Stage._process_with_retry`, the circuit breaker in `Stage.run` and the
advance-anyway `BusinessPermanentError` path were all unreachable. Every
client adapter now routes its failures through here.
"""
from typing import NoReturn

import httpx

from app.core.errors import TransientError, classify_http_error


def raise_for_status_code(status_code: int | None, provider: str,
                          detail: str) -> NoReturn:
    """Raise the taxonomy class that `status_code` maps to.

    A missing/unknown status code means the request never got far enough to
    receive one (transport failure), which is retryable — never data about
    the business.
    """
    if status_code is None or status_code <= 0:
        raise TransientError(f"{provider}: {detail}")
    cls = classify_http_error(status_code)
    raise cls(f"{provider}: HTTP {status_code}: {detail}", status_code=status_code)


def translate_httpx_error(exc: Exception, provider: str) -> NoReturn:
    """httpx flavour: status errors classify by code, transport errors
    (DNS, connect, read, timeout) are transient."""
    if isinstance(exc, httpx.HTTPStatusError):
        raise_for_status_code(exc.response.status_code, provider, str(exc))
    if isinstance(exc, httpx.TransportError):
        raise TransientError(f"{provider}: {exc!r}") from exc
    raise exc
