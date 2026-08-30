from datetime import datetime, timedelta

from app.domain.extractors.complaints import count_missed_call_complaints
from app.domain.extractors.serper import extract_serper_signals
from app.domain.extractors.html import HTML_SIGNAL_KEYS, extract_html_signals
from app.models.business import BusinessStatus
from app.models.derived import ApiCall, RawPayload, Review, Signals
from app.models.manual import ManualFacts
from app.pipeline.base import Stage

EXTRACTOR_VERSION = "1"

# Must match `collect_recent_reviews`'s own window (app/clients/
# serpapi_reviews.py), so re-deriving reproduces what fetch_reviews wrote.
REVIEW_WINDOW_DAYS = 90


class ExtractSignalsStage(Stage):
    name = "extract_signals"
    consumes = BusinessStatus.SITE_SCRAPED
    produces = BusinessStatus.SIGNALS_EXTRACTED

    def process(self, business, session) -> None:
        values = extract_serper_signals(
            business.opening_hours, business.booking_links,
            str(business.segment) if business.segment else None,
        )

        scrape = (session.query(RawPayload)
                  .filter_by(business_id=business.id, source="firecrawl")
                  .order_by(RawPayload.fetched_at.desc()).first())
        payload = scrape.payload if scrape else {}
        html_values = extract_html_signals(payload.get("raw_html"),
                                           payload.get("markdown"))
        # A signal the extractor did not evaluate is written as NULL, not
        # False: score.py drops NULL columns, so the rules that read it are
        # skipped and their points leave the denominator (on_missing: skip).
        # Writing every key explicitly also means a rebuild over a site that
        # has since gone dead cannot leave a stale True behind.
        for key in HTML_SIGNAL_KEYS:
            values[key] = html_values.get(key)
        values["website_status"] = payload.get("status", "none")

        values.update(self._review_signals(business, session))

        # Manual facts overlay LAST — they always win (ADR-008).
        manual = session.query(ManualFacts).filter_by(
            business_id=business.id).one_or_none()
        if manual is not None:
            if manual.estimated_employees is not None:
                values["estimated_employees"] = manual.estimated_employees
                values["employee_est_source"] = "manual_apollo"
            if manual.has_office_admin is not None:
                values["has_office_admin"] = manual.has_office_admin
            if manual.owner_growth_focused is not None:
                values["owner_growth_focused"] = manual.owner_growth_focused

        # extracted_at is NOT NULL with no DB-side default (see model); the
        # stage is the write path, so it stamps the timestamp itself.
        values["extracted_at"] = datetime.utcnow()

        existing = session.query(Signals).filter_by(
            business_id=business.id).one_or_none()
        if existing is None:
            session.add(Signals(business_id=business.id,
                                extractor_version=EXTRACTOR_VERSION, **values))
        else:
            for key, value in values.items():
                setattr(existing, key, value)
            existing.extractor_version = EXTRACTOR_VERSION

    def _review_signals(self, business, session) -> dict:
        """Re-derive the SerpApi-tier signals from the stored `Review` rows.

        Before this existed, `missed_call_complaints_90d` lived in exactly
        one place -- the `signals` row that fetch_reviews wrote once. The
        ADR-003-sanctioned recovery ("drop the derived tables, re-run the
        pure stages") therefore collapsed pain 45 -> 20 permanently, because
        the durable `api_calls` marker stops fetch_reviews ever
        re-selecting the business (C4).

        Keyed on that same `api_calls` marker rather than on the presence of
        a Review row, so a business whose lookup legitimately returned zero
        recent reviews is still recorded as "enriched, zero complaints"
        rather than falling back to unknown.
        """
        enriched = (session.query(ApiCall.id)
                    .filter(ApiCall.business_id == business.id,
                            ApiCall.provider == "serpapi")
                    .first())
        if enriched is None:
            # Never enriched: leave the review rules dormant (on_missing:
            # skip) instead of asserting zero complaints.
            return {}

        cutoff = datetime.utcnow() - timedelta(days=REVIEW_WINDOW_DAYS)
        reviews = (session.query(Review)
                   .filter(Review.business_id == business.id,
                           Review.source == "serpapi",
                           Review.published_at >= cutoff)
                   .all())
        count, quotes = count_missed_call_complaints(
            [r.text or "" for r in reviews])
        return {
            "missed_call_complaints_90d": count,
            "complaint_quotes": quotes,
            "review_velocity_90d": round(len(reviews) / 3, 1),
        }
