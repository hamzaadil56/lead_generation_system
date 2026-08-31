from datetime import datetime

from app.models.run import Run
from app.repositories.runs import claim_next_queued_run, get_run, list_runs


def _run(session, status="queued", source="ui", created=None):
    r = Run(status=status, source=source,
            search_plan={"vertical": "hvac", "location": "Houston, TX"},
            created_at=created or datetime(2026, 8, 31, 12, 0))
    session.add(r)
    session.commit()
    return r


def test_list_runs_returns_newest_first(session):
    _run(session, created=datetime(2026, 8, 1))
    _run(session, created=datetime(2026, 8, 20))
    _run(session, created=datetime(2026, 8, 10))

    rows, total = list_runs(session)

    assert total == 3
    assert [r.created_at.day for r in rows] == [20, 10, 1]


def test_list_runs_filters_by_status(session):
    _run(session, status="queued")
    _run(session, status="complete")

    rows, total = list_runs(session, status="complete")

    assert total == 1 and rows[0].status == "complete"


def test_get_run_returns_none_for_an_unknown_id(session):
    assert get_run(session, 999999) is None


def test_get_run_returns_the_run(session):
    r = _run(session)
    assert get_run(session, r.id).id == r.id


def test_claim_next_queued_run_takes_the_oldest_and_marks_it_running(session):
    old = _run(session, created=datetime(2026, 8, 1))
    _run(session, created=datetime(2026, 8, 20))

    claimed = claim_next_queued_run(session)

    assert claimed == old.id
    session.expire_all()
    assert session.query(Run).filter_by(id=old.id).one().status == "running"


def test_claim_next_queued_run_returns_none_when_nothing_is_queued(session):
    _run(session, status="complete")
    assert claim_next_queued_run(session) is None


def test_a_claimed_run_is_not_claimed_again(session):
    """The scheduler polls every 30s. A run claimed by one tick must not be
    picked up by the next while it is still executing."""
    _run(session)

    first = claim_next_queued_run(session)
    second = claim_next_queued_run(session)

    assert first is not None and second is None
