class ProviderError(Exception):
    """Base for the four-way provider taxonomy.

    Carries the originating HTTP status code (when there was one) so that
    stages can log an honest `api_calls` row for a call that failed instead
    of the unconditional `status_code=200` they used to write.
    """

    def __init__(self, message: str = "", status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class TransientError(ProviderError):
    """Retry with backoff: timeout, 429, 5xx."""


class BusinessPermanentError(ProviderError):
    """Not an error — data. Dead domain, 404. Business continues with
    reduced coverage rather than being marked failed."""


class RunPermanentError(ProviderError):
    """Abort the whole run: bad key, out of credits, quota exceeded."""


class BudgetExceeded(Exception):
    """The run's cost ceiling has been reached.

    Lives in `app.core` rather than `app.services.budget` so `app.pipeline`
    can catch it per business without importing the services layer;
    `app.services.budget` re-exports it for existing callers.
    """


class SearchPlanError(ValueError):
    """A vertical or state that is not in config -- a client mistake.

    Subclasses ValueError so existing `except ValueError` callers (and the
    generic setup handler in `execute_run`) keep working, but it is a
    NAMED type so the API can render exactly this as a 400. The app used
    to handle bare `ValueError`, and `pydantic.ValidationError` subclasses
    `ValueError`: every server-side DTO failure inside a router became a
    400 with the raw pydantic message -- internal field names, type
    errors, and truncated input values -- in the response body. That is
    what disguised a broken response schema as a bad request (C1/I1).
    Nothing else may be widened back into that handler.
    """


class RulesetVersionConflict(Exception):
    """A `rulesets` row already exists for this version with different
    content. Scoring must not proceed: it would overwrite every Score row
    written under the old definition (ADR-005)."""


def classify_http_error(status_code: int) -> type[ProviderError]:
    if status_code in (401, 402, 403):
        return RunPermanentError
    if status_code == 429 or status_code >= 500:
        return TransientError
    return BusinessPermanentError
