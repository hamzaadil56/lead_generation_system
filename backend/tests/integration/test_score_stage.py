from pathlib import Path
from app.models.business import Business, BusinessStatus
from app.models.derived import Signals, Score
from app.pipeline.score import ScoreStage
from app.services.rulesets import read_ruleset_file

RULESET = read_ruleset_file(Path("config/rulesets/hvac_v1.yaml"))


def _royal_air(session) -> Business:
    b = Business(cid="c1", name="Royal Air", status=BusinessStatus.SIGNALS_EXTRACTED)
    session.add(b); session.flush()
    session.add(Signals(business_id=b.id, booking_vendor="own",
                        has_booking_link=True, is_phone_only=False,
                        closed_weekends=True, closes_before_6pm=True,
                        has_chat_widget=False, runs_google_ads=True))
    session.commit()
    return b


def test_writes_a_score_with_reasons_and_quadrant(session):
    b = _royal_air(session)
    ScoreStage(RULESET).run(session, run_id=None)

    s = session.query(Score).filter_by(business_id=b.id).one()
    assert s.ruleset_version == "hvac_v1"
    assert s.quadrant == "go_now"
    assert s.coverage < 1.0                    # dormant review rules skipped
    assert any(r["rule"] == "closed_weekends" and r["matched"]
               for r in s.reasons)
    assert b.status is BusinessStatus.SCORED


def test_rescoring_with_the_same_ruleset_updates_rather_than_duplicates(session):
    b = _royal_air(session)
    ScoreStage(RULESET).run(session, run_id=None)
    b.status = BusinessStatus.SIGNALS_EXTRACTED
    session.commit()
    ScoreStage(RULESET).run(session, run_id=None)

    assert session.query(Score).filter_by(business_id=b.id).count() == 1


def test_a_second_ruleset_version_adds_a_row_rather_than_overwriting(session):
    """ADR-005: tuning must never destroy the evidence of the last attempt."""
    from dataclasses import replace
    b = _royal_air(session)
    ScoreStage(RULESET).run(session, run_id=None)
    b.status = BusinessStatus.SIGNALS_EXTRACTED
    session.commit()
    ScoreStage(replace(RULESET, version="hvac_v2")).run(session, run_id=None)

    versions = {s.ruleset_version
                for s in session.query(Score).filter_by(business_id=b.id)}
    assert versions == {"hvac_v1", "hvac_v2"}
