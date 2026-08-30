from datetime import datetime, timedelta, UTC
import serpapi
from app.clients.protocols import ReviewProvider, ReviewRecord, ReviewResult
from app.core.config import get_settings


class SerpApiReviewProvider:
    def __init__(self) -> None:
        self._key = get_settings().serpapi_key

    def reviews(self, data_id: str, page_token: str | None = None) -> ReviewResult:
        params = {
            "engine": "google_maps_reviews",
            "data_id": data_id,
            "sort_by": "newestFirst",   # MANDATORY — the default qualityScore
                                        # ordering returns an arbitrary slice of
                                        # history and corrupts velocity (ADR-020)
            "num": 20,
            "api_key": self._key,
        }
        if page_token:
            params["next_page_token"] = page_token
        raw = serpapi.search(**params).as_dict()

        return ReviewResult(
            reviews=[
                ReviewRecord(
                    rating=r.get("rating"), iso_date=r.get("iso_date"),
                    snippet=r.get("snippet") or r.get("extracted_snippet"),
                    author=(r.get("user") or {}).get("name"),
                )
                for r in raw.get("reviews", [])
            ],
            next_page_token=(raw.get("serpapi_pagination") or {}).get("next_page_token"),
            raw=raw,
        )


def parse_iso_date(iso_date: str) -> datetime | None:
    """Parse a review's iso_date into an aware UTC datetime.

    SerpApi's exact date format has never been observed in production, so
    this must tolerate whatever comes back rather than crash the whole
    collection call for one bad record:
      - malformed string -> None (caller skips the review)
      - naive result -> treated as UTC (SerpApi timestamps are UTC in
        practice; dropping an otherwise-good review would silently
        understate review_velocity_90d)
      - already-aware result -> returned as-is
    """
    try:
        parsed = datetime.fromisoformat(iso_date)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def collect_recent_reviews(provider: ReviewProvider, data_id: str,
                           days: int = 90, max_pages: int = 4) -> list[ReviewRecord]:
    """Page newest-first, stopping at the first page with nothing recent."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    collected: list[ReviewRecord] = []
    token: str | None = None

    for _ in range(max_pages):
        result = provider.reviews(data_id, token)
        recent = []
        for r in result.reviews:
            if not r.iso_date:
                continue
            parsed = parse_iso_date(r.iso_date)
            if parsed is not None and parsed >= cutoff:
                recent.append(r)
        collected.extend(recent)
        if not recent or not result.next_page_token:
            break
        token = result.next_page_token

    return collected
