import httpx
from app.clients.protocols import PlaceRecord, SearchResult
from app.core.config import get_settings

ENDPOINT = "https://google.serper.dev/maps"


def parse_search_response(raw: dict) -> SearchResult:
    records = [
        PlaceRecord(
            cid=p["cid"], place_id=p.get("placeId"), fid=p.get("fid"),
            title=p["title"], address=p.get("address"),
            latitude=p.get("latitude"), longitude=p.get("longitude"),
            rating=p.get("rating"), rating_count=p.get("ratingCount"),
            phone_number=p.get("phoneNumber"), website=p.get("website"),
            type=p.get("type"), types=p.get("types", []),
            opening_hours=p.get("openingHours"),
            booking_links=p.get("bookingLinks"),   # absent stays None, not []
            raw=p,
        )
        for p in raw.get("places", [])
    ]
    return SearchResult(records=records, credits=raw.get("credits", 0), raw=raw)


class SerperClient:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._settings = get_settings()
        self._client = client or httpx.Client(timeout=30.0)

    def search(self, query: str, page: int = 1) -> SearchResult:
        resp = self._client.post(
            ENDPOINT,
            headers={"X-API-KEY": self._settings.serper_key,
                     "Content-Type": "application/json"},
            json={"q": query, "gl": "us", "hl": "en", "page": page},
        )
        resp.raise_for_status()
        return parse_search_response(resp.json())
