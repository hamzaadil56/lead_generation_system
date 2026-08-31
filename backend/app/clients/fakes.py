import json
from pathlib import Path
from app.clients.protocols import (
    SearchResult, ScrapeResult, ReviewResult, ReviewRecord)
from app.clients.serper import parse_search_response

FIXTURES = Path(__file__).parent.parent.parent / "tests" / "fixtures"


class FakeSearchProvider:
    """Replays the real Houston fixture. Zero API spend in tests."""

    def __init__(self, fixture: str = "serper_maps_houston_hvac.json") -> None:
        self._raw = json.loads((FIXTURES / fixture).read_text())
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, page: int = 1) -> SearchResult:
        self.calls.append((query, page))
        if page > 1:
            return SearchResult(records=[], credits=1, raw={"places": []})
        return parse_search_response(self._raw)


class FakeWebScraper:
    def __init__(self, html: str = "<html><body>hi</body></html>") -> None:
        self._html = html
        self.calls: list[str] = []

    def scrape(self, url: str) -> ScrapeResult:
        self.calls.append(url)
        return ScrapeResult(url=url, markdown="hi", raw_html=self._html,
                            links=[], status="ok", raw={})


class FakeReviewProvider:
    def __init__(self, reviews: list[ReviewRecord] | None = None) -> None:
        self._reviews = reviews or []
        self.calls: list[str] = []

    def reviews(self, data_id: str, page_token: str | None = None) -> ReviewResult:
        self.calls.append(data_id)
        return ReviewResult(reviews=self._reviews, next_page_token=None, raw={})
