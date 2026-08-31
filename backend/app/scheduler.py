"""In-process scheduling (ADR-010). One container, no Redis, no Celery.

Every job swallows its own exceptions. An exception escaping into an
APScheduler worker thread removes the job for the remaining life of the
process, and nothing would say so.
"""
from datetime import datetime, timedelta

import structlog
from apscheduler.schedulers.background import BackgroundScheduler

from app.core.db import get_session
from app.models.business import Business, BusinessStatus
from app.models.run import Run
from app.repositories.runs import claim_next_queued_run
from app.services.run_executor import execute_run

log = structlog.get_logger()

__all__ = ["build_scheduler", "poll_queued_runs", "refresh_stale_businesses",
           "reset_stuck_runs", "retry_failed_businesses"]


def poll_queued_runs() -> int | None:
    """Claim one queued run and execute it. Returns the run id, or None."""
    try:
        with get_session() as s:
            run_id = claim_next_queued_run(s)
        if run_id is None:
            return None
        log.info("scheduler.run_claimed", run_id=run_id)
        execute_run(run_id)
        return run_id
    except Exception:
        # execute_run has already written the terminal Run state on both
        # the budget and crash paths, so nothing is stranded by catching
        # here; this only stops the exception from killing the polling job
        # for the remaining life of the process.
        log.exception("scheduler.poll_failed")
        return None


def reset_stuck_runs(max_age_hours: int = 1) -> int:
    """A run left `running` past the cutoff goes back to `queued`.

    Covers the case where the process died mid-run: without this the run is
    stranded and the poller will never look at it again.
    """
    try:
        cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
        with get_session() as s:
            rows = (s.query(Run)
                    .filter(Run.status == "running",
                            Run.started_at.isnot(None),
                            Run.started_at < cutoff).all())
            for run in rows:
                run.status = "queued"
                run.started_at = None
            s.commit()
            if rows:
                log.warning("scheduler.reset_stuck_runs", count=len(rows))
            return len(rows)
    except Exception:
        log.exception("scheduler.reset_stuck_runs_failed")
        return 0


def retry_failed_businesses(max_attempts: int = 3) -> int:
    """Send FAILED businesses back to the start of the pipeline, under a cap.

    The cap matters: without it a permanently broken row is retried nightly
    forever, and each retry that reaches a provider costs money. The
    comparison is strict (`< max_attempts`), so a row that has already used
    its three attempts is left alone.
    """
    try:
        with get_session() as s:
            rows = (s.query(Business)
                    .filter(Business.status == BusinessStatus.FAILED,
                            Business.attempt_count < max_attempts).all())
            for business in rows:
                business.status = BusinessStatus.DISCOVERED
                business.failed_stage = None
                business.error_message = None
            s.commit()
            if rows:
                log.info("scheduler.retry_failed", count=len(rows))
            return len(rows)
    except Exception:
        log.exception("scheduler.retry_failed_businesses_failed")
        return 0


def refresh_stale_businesses(older_than_days: int = 90) -> int:
    """Re-walk businesses whose data has aged out (spec section 5, Refresh).

    Selection is on `updated_at` only. `review_count` is a segment label,
    never a filter or a sort key.
    """
    try:
        cutoff = datetime.utcnow() - timedelta(days=older_than_days)
        with get_session() as s:
            rows = (s.query(Business)
                    .filter(Business.status == BusinessStatus.SCORED,
                            Business.updated_at < cutoff).all())
            for business in rows:
                business.status = BusinessStatus.DISCOVERED
            s.commit()
            if rows:
                log.info("scheduler.refresh_stale", count=len(rows))
            return len(rows)
    except Exception:
        log.exception("scheduler.refresh_stale_businesses_failed")
        return 0


def build_scheduler() -> BackgroundScheduler:
    """Wire the three recurring jobs. `max_instances=1` on the poller stops a
    slow run from being started twice while the first is still going.

    `reset_stuck_runs` is deliberately NOT among them. It was registered on
    an hourly timer for one round and removed: a timed reconciler cannot
    tell a run abandoned by a dead process from one still executing in this
    one. `execute_run` stamps `started_at` once and never refreshes it, so
    any run still going past the cutoff was flipped back to `queued`
    mid-flight and the next 30-second poll re-claimed and concurrently
    re-executed the same run_id -- double billing, two writers on the same
    rows. Fixing that properly needs a heartbeat column, which is DDL this
    plan does not have. The startup call in the app's lifespan has no such
    race and covers the case that matters; see the comment there before
    re-adding a timer here.
    """
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(poll_queued_runs, "interval", seconds=30,
                      id="poll_queued_runs", max_instances=1,
                      coalesce=True, replace_existing=True)
    scheduler.add_job(retry_failed_businesses, "cron", hour=3, minute=0,
                      id="retry_failed_businesses", replace_existing=True)
    scheduler.add_job(refresh_stale_businesses, "cron", day=1, hour=4, minute=0,
                      id="refresh_stale_businesses", replace_existing=True)
    return scheduler
