from datetime import datetime

import structlog
from sqlalchemy import and_, func
from sqlalchemy.orm import aliased

from app.clients.protocols import ReviewProvider, ReviewResult
from app.clients.serpapi_reviews import collect_recent_reviews, parse_iso_date
from app.core.errors import ProviderError, RunPermanentError
from app.domain.extractors.complaints import count_missed_call_complaints
from app.models.business import Business, BusinessStatus
from app.models.derived import ApiCall, RawPayload, Review, Score, Signals
from app.pipeline.base import StageReport

log = structlog.get_logger()

# collect_recent_reviews's own `max_pages` default (app/clients/
# serpapi_reviews.py) — the worst case for one business's real cost. The
# ceiling pre-check reserves this many credits *before* calling the
# provider, so the configured monthly cap can never be exceeded regardless
# of how many pages a business's reviews happen to span.
MAX_CALLS_PER_BUSINESS = 4


class _CountingReviewProvider:
    """Wraps a real `ReviewProvider`, counting how many calls actually
    completed (and therefore billed) and keeping each page's raw response.
    `collect_recent_reviews` makes between 1 and `max_pages` calls
    depending on paging, so this is the only way to log the *actual* cost
    of a business's enrichment instead of a fixed guess."""

    def __init__(self, inner: ReviewProvider) -> None:
        self._inner = inner
        self.calls = 0
        # Every page's untouched response, so the stage can write one
        # RawPayload per real call. `reviews`/`signals` are declared
        # rebuildable (ADR-003) and cannot be unless this is stored.
        self.raw_pages: list[dict] = []

    def reviews(self, data_id: str, page_token: str | None = None) -> ReviewResult:
        # Counted AFTER the call returns: a page that raised consumed no
        # SerpApi credit, and `credits` must be the actual cost, not the
        # number of attempts.
        result = self._inner.reviews(data_id, page_token)
        self.calls += 1
        self.raw_pages.append(result.raw)
        return result


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
        # Sum credits, not rows: each ApiCall row can carry >1 credit
        # (Finding 1). coalesce(..., 0) so a month with no calls yet reads
        # as 0 rather than NULL/None.
        total = (session.query(func.coalesce(func.sum(ApiCall.credits), 0))
                 .filter(ApiCall.provider == "serpapi",
                         ApiCall.created_at >= start)
                 .scalar())
        return int(total)

    def run(self, session, run_id: int | None) -> StageReport:
        report = StageReport()
        spent = self._spent_this_month(session)

        # "Already enriched" is marked by a durable `api_calls` row, not by
        # the presence of a `Review` row: a business whose SerpApi lookup
        # legitimately returns zero recent reviews never gets a `Review`
        # row written, but it must still never be re-selected/re-billed.
        # `api_calls` is permanent and never pruned, so this marker holds
        # even after the business loops back through extract_signals/score.
        serpapi_calls = aliased(ApiCall)
        candidates = (session.query(Business)
                      .join(Score, Score.business_id == Business.id)
                      .outerjoin(serpapi_calls,
                                and_(serpapi_calls.business_id == Business.id,
                                     serpapi_calls.provider == "serpapi"))
                      .filter(Business.status == BusinessStatus.SCORED,
                              serpapi_calls.id.is_(None))
                      .order_by(Score.fit_score.desc())
                      .limit(self._top_n).all())

        for business in candidates:
            if spent + MAX_CALLS_PER_BUSINESS > self._ceiling:
                report.reason = (f"SerpApi monthly ceiling reached "
                                 f"({spent}/{self._ceiling})")
                log.warning("fetch_reviews.ceiling_reached", spent=spent)
                break

            wrapper = _CountingReviewProvider(self._provider)
            # The ApiCall row is written in `finally`, not after a
            # successful return: `collect_recent_reviews` makes 1-4 real
            # calls and a failure on page 3 used to consume two real
            # credits with no row ever written -- invisible to
            # `_spent_this_month`, so the 250/month free ceiling was
            # computed from an undercount (I2). This stage is not a `Stage`
            # subclass, so it inherits none of base.py's protections and
            # had no try/except of any kind.
            failure: ProviderError | None = None
            try:
                reviews = collect_recent_reviews(wrapper, business.cid)
            except ProviderError as exc:
                failure = exc
                reviews = []
            finally:
                spent += wrapper.calls
                session.add(ApiCall(
                    run_id=run_id, business_id=business.id,
                    provider="serpapi", endpoint="google_maps_reviews",
                    credits=wrapper.calls,
                    status_code=(failure.status_code if failure else 200),
                    created_at=datetime.utcnow()))
                session.commit()

            if failure is not None:
                report.failed += 1
                log.warning("fetch_reviews.business_failed", cid=business.cid,
                            error=str(failure))
                if isinstance(failure, RunPermanentError):
                    # A dead key fails identically for every remaining
                    # business; do not burn the whole candidate list on it.
                    report.aborted = True
                    report.reason = str(failure)
                    break
                # The business keeps its SCORED status so a later run can
                # retry it; only the ApiCall marker would block that, and
                # a partial-credit row is the honest record of what was
                # actually billed.
                continue
            # One permanent payload per real call (ADR-003). `derived.py`
            # already lists `serpapi_reviews` as an expected source; nothing
            # was ever writing it, so the documented "drop the derived
            # tables and re-run" recovery destroyed the enrichment for good.
            for page in wrapper.raw_pages:
                session.add(RawPayload(business_id=business.id,
                                       source="serpapi_reviews", url=None,
                                       payload=page,
                                       fetched_at=datetime.utcnow()))

            for r in reviews:
                published_at = None
                if r.iso_date:
                    parsed = parse_iso_date(r.iso_date)
                    # Normalise to naive UTC: Review.published_at is a naive
                    # DateTime column, and parse_iso_date always returns an
                    # aware datetime (or None) — exactly one representation
                    # must ever reach this column.
                    if parsed is not None:
                        published_at = parsed.replace(tzinfo=None)
                session.add(Review(
                    business_id=business.id, rating=r.rating, text=r.snippet,
                    author=r.author, published_at=published_at,
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
