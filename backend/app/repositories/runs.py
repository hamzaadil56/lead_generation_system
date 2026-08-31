"""Read queries for runs, plus the scheduler's claim (ADR-024)."""
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.run import Run
from app.schemas.runs import RunOut


def list_runs(session: Session, status: str | None = None, page: int = 1,
              page_size: int = 50) -> tuple[list[RunOut], int]:
    q = session.query(Run)
    if status:
        q = q.filter(Run.status == status)
    # NOT `q.with_entities(func.count()).order_by(None).scalar()`: with no
    # filter applied, `session.query(Run)` carries no explicit FROM/filter
    # clause, and with_entities() then drops the implicit FROM entirely --
    # the resulting `SELECT count(*)` (no FROM) returns 1 regardless of
    # table size. `.count()` wraps the query as a subquery instead, so it
    # is correct whether or not a filter was applied.
    total = q.order_by(None).count()
    rows = (q.order_by(Run.created_at.desc().nullslast(), Run.id.desc())
             .offset((page - 1) * page_size).limit(page_size).all())
    return [RunOut.model_validate(r) for r in rows], total


def get_run(session: Session, run_id: int) -> RunOut | None:
    row = session.query(Run).filter_by(id=run_id).one_or_none()
    return RunOut.model_validate(row) if row else None


def claim_next_queued_run(session: Session) -> int | None:
    """Take the oldest `queued` run and mark it `running`, atomically.

    `with_for_update(skip_locked=True)` is what makes the claim safe: a
    second poller skips the locked row instead of blocking on it or, worse,
    claiming the same run. The spec's known limitation -- two FastAPI
    instances double-executing -- is exactly what this prevents, so the
    Postgres advisory lock it mentions is not needed yet.
    """
    row = (session.query(Run)
           .filter(Run.status == "queued")
           .order_by(Run.created_at.asc().nullsfirst(), Run.id.asc())
           .with_for_update(skip_locked=True)
           .first())
    if row is None:
        return None
    row.status = "running"
    row.started_at = datetime.utcnow()
    session.commit()
    return row.id
