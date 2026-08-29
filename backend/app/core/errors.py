class TransientError(Exception):
    """Retry with backoff: timeout, 429, 5xx."""


class BusinessPermanentError(Exception):
    """Not an error — data. Dead domain, 404. Business continues with
    reduced coverage rather than being marked failed."""


class RunPermanentError(Exception):
    """Abort the whole run: bad key, out of credits, quota exceeded."""


def classify_http_error(status_code: int) -> type[Exception]:
    if status_code in (401, 402, 403):
        return RunPermanentError
    if status_code == 429 or status_code >= 500:
        return TransientError
    return BusinessPermanentError
