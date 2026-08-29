from abc import ABC, abstractmethod
from dataclasses import dataclass

import structlog
from sqlalchemy.orm import Session
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.errors import BusinessPermanentError, RunPermanentError, TransientError
from app.models.business import Business, BusinessStatus

log = structlog.get_logger()
CIRCUIT_BREAKER_THRESHOLD = 5


@dataclass
class StageReport:
    processed: int = 0
    failed: int = 0
    aborted: bool = False
    reason: str | None = None


class Stage(ABC):
    """Template Method: retry, error capture, and status advancement are
    written once here; subclasses supply only `process`."""

    name: str
    consumes: BusinessStatus
    produces: BusinessStatus

    @abstractmethod
    def process(self, business: Business, session: Session) -> None: ...

    def select(self, session: Session, run_id: int | None, limit: int) -> list[Business]:
        q = session.query(Business).filter(Business.status == self.consumes)
        return q.limit(limit).all()

    @retry(retry=retry_if_exception_type(TransientError),
           stop=stop_after_attempt(3),
           wait=wait_exponential(multiplier=1, min=1, max=16), reraise=True)
    def _process_with_retry(self, business: Business, session: Session) -> None:
        self.process(business, session)

    def run(self, session: Session, run_id: int | None, limit: int = 500) -> StageReport:
        report = StageReport()
        consecutive_fatal = 0

        for business in self.select(session, run_id, limit):
            try:
                # A SAVEPOINT scopes rollback to *this business only*: on
                # failure only this unit of work unwinds, leaving prior
                # committed businesses (and the outer transaction) intact.
                # Plain session.rollback() would roll back the whole
                # transaction the Session participates in, which is too
                # coarse for per-business isolation (see ADR-009 note below).
                with session.begin_nested():
                    self._process_with_retry(business, session)
                    business.status = self.produces
                session.commit()          # Unit of Work per business (ADR-009)
                report.processed += 1
                consecutive_fatal = 0

            except RunPermanentError as exc:
                consecutive_fatal += 1
                report.failed += 1
                if consecutive_fatal >= CIRCUIT_BREAKER_THRESHOLD:
                    report.aborted = True
                    report.reason = str(exc)
                    log.error("stage.aborted", stage=self.name, reason=str(exc))
                    break

            except BusinessPermanentError:
                with session.begin_nested():
                    business.status = self.produces      # data, not failure
                session.commit()
                report.processed += 1

            except Exception as exc:
                business.status = BusinessStatus.FAILED
                business.failed_stage = self.name
                business.error_message = str(exc)[:500]
                business.attempt_count += 1
                session.commit()
                report.failed += 1
                log.warning("stage.business_failed", stage=self.name,
                            cid=business.cid, error=str(exc))

        return report
