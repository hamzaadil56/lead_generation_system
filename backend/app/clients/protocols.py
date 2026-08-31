from typing import Protocol
from pydantic import BaseModel


class PlaceRecord(BaseModel):
    cid: str
    place_id: str | None = None
    fid: str | None = None
    title: str
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    rating: float | None = None
    rating_count: int | None = None
    phone_number: str | None = None
    website: str | None = None
    type: str | None = None
    types: list[str] = []
    opening_hours: dict[str, str] | None = None
    booking_links: list[str] | None = None
    raw: dict


class SearchResult(BaseModel):
    records: list[PlaceRecord]
    credits: int
    raw: dict


class ScrapeResult(BaseModel):
    url: str
    markdown: str | None = None
    raw_html: str | None = None
    links: list[str] = []
    status: str            # "ok" | "dead" | "parked"
    # The TARGET site's HTTP status, when the provider reported one. Used by
    # scrape_site so the `api_calls` row records what actually happened
    # instead of an unconditional 200.
    status_code: int | None = None
    raw: dict


class ReviewRecord(BaseModel):
    rating: int | None = None
    iso_date: str | None = None
    snippet: str | None = None
    author: str | None = None


class ReviewResult(BaseModel):
    reviews: list[ReviewRecord]
    next_page_token: str | None = None
    raw: dict


class SearchProvider(Protocol):
    def search(self, query: str, page: int = 1) -> SearchResult: ...


class WebScraper(Protocol):
    def scrape(self, url: str) -> ScrapeResult: ...


class ReviewProvider(Protocol):
    def reviews(self, data_id: str, page_token: str | None = None) -> ReviewResult: ...
