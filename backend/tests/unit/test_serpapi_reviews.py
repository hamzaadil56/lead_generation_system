from datetime import datetime, timedelta, UTC
from app.clients.protocols import ReviewRecord, ReviewResult
from app.clients.serpapi_reviews import collect_recent_reviews


def _iso(days_ago: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()


class PagedProvider:
    """Page 1 returns 8 regardless of `num`; later pages up to 20 (ADR-020)."""

    def __init__(self, pages: list[list[ReviewRecord]]) -> None:
        self.pages = pages
        self.call_count = 0

    def reviews(self, data_id: str, page_token: str | None = None) -> ReviewResult:
        idx = self.call_count
        self.call_count += 1
        has_next = idx + 1 < len(self.pages)
        return ReviewResult(reviews=self.pages[idx],
                            next_page_token="tok" if has_next else None, raw={})


def test_stops_as_soon_as_reviews_pass_the_90_day_boundary():
    p = PagedProvider([
        [ReviewRecord(iso_date=_iso(5)) for _ in range(8)],
        [ReviewRecord(iso_date=_iso(200)) for _ in range(20)],   # all too old
        [ReviewRecord(iso_date=_iso(400)) for _ in range(20)],
    ])
    out = collect_recent_reviews(p, "cid1")
    assert len(out) == 8
    assert p.call_count == 2      # stopped after the first stale page — not 3


def test_keeps_paginating_while_reviews_are_recent():
    p = PagedProvider([
        [ReviewRecord(iso_date=_iso(3)) for _ in range(8)],
        [ReviewRecord(iso_date=_iso(30)) for _ in range(20)],
        [ReviewRecord(iso_date=_iso(300)) for _ in range(20)],
    ])
    out = collect_recent_reviews(p, "cid1")
    assert len(out) == 28


def test_respects_max_pages_ceiling():
    p = PagedProvider([[ReviewRecord(iso_date=_iso(1))] * 20 for _ in range(10)])
    collect_recent_reviews(p, "cid1", max_pages=4)
    assert p.call_count == 4      # a runaway business cannot drain the free tier


def test_reviews_without_dates_are_skipped_not_crashed():
    p = PagedProvider([[ReviewRecord(iso_date=None), ReviewRecord(iso_date=_iso(2))]])
    assert len(collect_recent_reviews(p, "cid1")) == 1


def test_naive_iso_date_within_window_is_kept_not_dropped():
    """SerpApi's exact date format has never been observed live. A
    timezone-naive timestamp (no offset) must be treated as UTC and kept,
    not silently dropped, or review_velocity_90d would be understated."""
    naive = (datetime.now(UTC) - timedelta(days=5)).replace(tzinfo=None).isoformat()
    p = PagedProvider([[ReviewRecord(iso_date=naive)]])
    assert len(collect_recent_reviews(p, "cid1")) == 1


def test_malformed_iso_date_is_skipped_not_crashed():
    """One bad record must not kill the whole enrichment pass (Task 16 calls
    this for every enriched lead)."""
    p = PagedProvider([[
        ReviewRecord(iso_date="not-a-date"),
        ReviewRecord(iso_date=_iso(2)),
    ]])
    assert len(collect_recent_reviews(p, "cid1")) == 1


def test_z_suffixed_iso_date_parses_and_compares_correctly():
    """The Z suffix is the format most likely to come back from the real
    API and must not regress."""
    z_suffixed = (datetime.now(UTC) - timedelta(days=5)).isoformat().replace("+00:00", "Z")
    p = PagedProvider([[ReviewRecord(iso_date=z_suffixed)]])
    assert len(collect_recent_reviews(p, "cid1")) == 1
