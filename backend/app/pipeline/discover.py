from collections.abc import Callable
from datetime import datetime

import structlog
from sqlalchemy.orm import Session
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.clients.protocols import SearchProvider, PlaceRecord
from app.core.errors import (
    BudgetExceeded,
    BusinessPermanentError,
    RunPermanentError,
    TransientError,
)
from app.domain.segments import segment_for
from app.domain.phone import validate_phone
from app.models.business import Business, BusinessStatus
from app.models.derived import RawPayload, ApiCall
from app.models.run import RunBusiness, SearchQuery
from app.pipeline.base import StageReport
from app.services.search_plan import SearchPlan

log = structlog.get_logger()


class DiscoverStage:
    """Not a `Stage` subclass: discover *creates* businesses rather than
    consuming a status, so it doesn't fit the Stage template method."""

    name = "discover"

    def __init__(self, provider: SearchProvider) -> None:
        self._provider = provider

    # DiscoverStage is not a `Stage`, so it inherits none of base.py's
    # protections and must carry its own. Same policy as
    # `Stage._process_with_retry`: 3 attempts with backoff on a
    # TransientError, which is what a Serper 429 or 5xx now raises. Before
    # the clients spoke the taxonomy, a 429 arrived as a raw
    # httpx.HTTPStatusError and killed the run after ONE attempt (C2).
    @retry(retry=retry_if_exception_type(TransientError),
           stop=stop_after_attempt(3),
           wait=wait_exponential(multiplier=1, min=1, max=16), reraise=True)
    def _search(self, query: str, page: int):
        return self._provider.search(query, page=page)

    def discover(self, session: Session, run_id: int | None,
                 plan: SearchPlan,
                 budget_check: Callable[[Session], None] | None = None
                 ) -> StageReport:
        report = StageReport()

        for query in plan.queries:
            for page in range(1, plan.pages_per_query + 1):
                # Checked before each paid call, not once per stage (I1).
                if budget_check is not None:
                    try:
                        budget_check(session)
                    except BudgetExceeded as exc:
                        report.aborted = True
                        report.reason = str(exc)
                        log.warning("discover.budget_exceeded", reason=str(exc))
                        session.commit()
                        return report
                try:
                    result = self._search(query, page)
                except RunPermanentError as exc:
                    # Bad key / out of credits: every remaining query would
                    # fail the same way. Stop and say so rather than
                    # reporting a short run as a successful one.
                    report.aborted = True
                    report.reason = str(exc)
                    log.error("discover.aborted", reason=str(exc))
                    session.commit()
                    return report
                except BusinessPermanentError as exc:
                    log.warning("discover.query_failed", term=query,
                                page=page, error=str(exc))
                    report.failed += 1
                    break

                session.add(ApiCall(run_id=run_id, provider="serper",
                                    endpoint="maps", credits=result.credits,
                                    status_code=200,
                                    created_at=datetime.utcnow()))
                session.add(SearchQuery(run_id=run_id, term=query,
                                        location=None,
                                        result_count=len(result.records),
                                        executed_at=datetime.utcnow()))
                if not result.records:
                    break

                for record in result.records:
                    self._upsert(session, run_id, record, plan.vertical, report)

                session.commit()

        return report

    def _upsert(self, session: Session, run_id: int | None, record: PlaceRecord,
                vertical: str, report: StageReport) -> None:
        existing = session.query(Business).filter_by(cid=record.cid).one_or_none()

        if existing is not None:
            # ON CONFLICT DO NOTHING: status is untouched, so this business
            # falls out of every downstream stage query (ADR-013).
            if run_id is not None:
                session.merge(RunBusiness(run_id=run_id,
                                          business_id=existing.id, is_new=False))
            return

        phone = validate_phone(record.phone_number)
        business = Business(
            cid=record.cid, place_id=record.place_id, fid=record.fid,
            name=record.title, address=record.address,
            lat=record.latitude, lng=record.longitude,
            phone=phone, phone_is_valid=phone is not None,
            website=record.website,
            rating=record.rating, review_count=record.rating_count,
            segment=segment_for(record.rating_count),
            primary_category=record.type, types=record.types,
            opening_hours=record.opening_hours,
            booking_links=record.booking_links,
            vertical=vertical,
            # The ONLY prefilter is "has a website" (ADR-022).
            status=(BusinessStatus.DISCOVERED if record.website
                    else BusinessStatus.FILTERED_OUT),
            first_seen_run_id=run_id,
        )
        session.add(business)
        session.flush()

        session.add(RawPayload(business_id=business.id, source="serper_maps",
                               url=None, payload=record.raw,
                               fetched_at=datetime.utcnow()))
        if run_id is not None:
            session.add(RunBusiness(run_id=run_id, business_id=business.id,
                                    is_new=True))
        report.processed += 1
