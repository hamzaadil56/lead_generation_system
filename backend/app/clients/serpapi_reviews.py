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


def collect_recent_reviews(provider: ReviewProvider, data_id: str,
                           days: int = 90, max_pages: int = 4) -> list[ReviewRecord]:
    """Page newest-first, stopping at the first page with nothing recent."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    collected: list[ReviewRecord] = []
    token: str | None = None

    for _ in range(max_pages):
        result = provider.reviews(data_id, token)
        recent = [
            r for r in result.reviews
            if r.iso_date and datetime.fromisoformat(r.iso_date) >= cutoff
        ]
        collected.extend(recent)
        if not recent or not result.next_page_token:
            break
        token = result.next_page_token

    return collected
