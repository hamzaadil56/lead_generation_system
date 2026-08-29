from datetime import datetime

import structlog

from app.clients.protocols import ReviewProvider
from app.clients.serpapi_reviews import collect_recent_reviews
from app.domain.extractors.complaints import count_missed_call_complaints
from app.models.business import Business, BusinessStatus
from app.models.derived import Score, Review, Signals, ApiCall
from app.pipeline.base import StageReport

log = structlog.get_logger()
CALLS_PER_BUSINESS = 2      # page 1 returns 8, page 2 up to 20 (ADR-020)


class FetchReviewsStage:
    """Not a `Stage` subclass: this stage selects `SCORED` businesses by
    score and resets them backwards to `SITE_SCRAPED` rather than consuming
    a plain status forward, so it doesn't fit the Stage template method."""

    name = "fetch_reviews"

    def __init__(self, provider: ReviewProvider, top_n: int = 25,
                 monthly_ceiling: int = 250) -> None:
        self._provider = provider
        self._top_n = top_n
        self._ceiling = monthly_ceiling

    def _spent_this_month(self, session) -> int:
        # Naive on purpose: ApiCall.created_at is stored naive throughout
        # this schema (see discover.py / scrape_site.py, which both stamp
        # it with datetime.utcnow()), so the comparison below stays
        # naive-vs-naive and cannot raise the aware/naive TypeError we hit
        # earlier in serpapi_reviews.py.
        start = datetime.utcnow().replace(day=1, hour=0, minute=0,
                                          second=0, microsecond=0)
        return (session.query(ApiCall)
                .filter(ApiCall.provider == "serpapi",
                        ApiCall.created_at >= start).count())

    def run(self, session, run_id: int | None) -> StageReport:
        report = StageReport()
        spent = self._spent_this_month(session)

        candidates = (session.query(Business)
                      .join(Score, Score.business_id == Business.id)
                      .outerjoin(Review, Review.business_id == Business.id)
                      .filter(Business.status == BusinessStatus.SCORED,
                              Review.id.is_(None))       # not already enriched
                      .order_by(Score.fit_score.desc())
                      .limit(self._top_n).all())

        for business in candidates:
            if spent + CALLS_PER_BUSINESS > self._ceiling:
                report.reason = (f"SerpApi monthly ceiling reached "
                                 f"({spent}/{self._ceiling})")
                log.warning("fetch_reviews.ceiling_reached", spent=spent)
                break

            reviews = collect_recent_reviews(self._provider, business.cid)
            spent += CALLS_PER_BUSINESS
            session.add(ApiCall(run_id=run_id, provider="serpapi",
                                endpoint="google_maps_reviews",
                                credits=CALLS_PER_BUSINESS, status_code=200,
                                created_at=datetime.utcnow()))

            for r in reviews:
                session.add(Review(
                    business_id=business.id, rating=r.rating, text=r.snippet,
                    author=r.author,
                    published_at=datetime.fromisoformat(r.iso_date)
                    if r.iso_date else None,
                    source="serpapi"))

            count, quotes = count_missed_call_complaints(
                [r.snippet or "" for r in reviews])
            sig = session.query(Signals).filter_by(
                business_id=business.id).one_or_none()
            if sig is not None:
                sig.missed_call_complaints_90d = count
                sig.complaint_quotes = quotes
                sig.review_velocity_90d = round(len(reviews) / 3, 1)

            # Loop back so extract_signals and score re-run over richer data.
            business.status = BusinessStatus.SITE_SCRAPED
            session.commit()
            report.processed += 1

        return report
