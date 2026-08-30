from pathlib import Path

import pytest

from app.models.business import Business, BusinessStatus
from app.models.derived import Signals, Score
from app.pipeline.score import ScoreStage
from app.services.rulesets import read_ruleset_definition, read_ruleset_file

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


DEFINITION = read_ruleset_definition(Path("config/rulesets/hvac_v1.yaml"))


def test_scoring_records_the_ruleset_definition_it_used(session):
    """I5/ADR-005: rules are supposed to be 'defined as JSON/YAML in a
    `rulesets` table' so that 'old versions are never mutated'. The table
    existed in the model and the migration and nothing ever wrote a row —
    scoring read a mutable YAML file off disk on every invocation."""
    from app.models.manual import Ruleset as RulesetRow
    b = _royal_air(session)
    ScoreStage(RULESET, definition=DEFINITION).run(session, run_id=None)

    row = session.query(RulesetRow).filter_by(version="hvac_v1").one()
    assert row.vertical == "hvac"
    assert row.definition == DEFINITION


def test_rescoring_with_an_unchanged_ruleset_is_idempotent(session):
    from app.models.manual import Ruleset as RulesetRow
    b = _royal_air(session)
    ScoreStage(RULESET, definition=DEFINITION).run(session, run_id=None)
    b.status = BusinessStatus.SIGNALS_EXTRACTED
    session.commit()
    ScoreStage(RULESET, definition=DEFINITION).run(session, run_id=None)

    assert session.query(RulesetRow).filter_by(version="hvac_v1").count() == 1


def test_editing_a_ruleset_without_bumping_its_version_fails_loudly(session):
    """The reproduction: tune `closed_weekends` from 30 to 40 points in
    hvac_v1.yaml and re-run `score`. `score.py` found the existing
    (business_id, "hvac_v1") row and updated it IN PLACE, destroying every
    previous score and any record of what the rules were when they were
    written — exactly what ADR-005 exists to prevent, on the default path.
    """
    import copy
    from app.core.errors import RulesetVersionConflict
    from app.domain.rules.loader import load_ruleset

    b = _royal_air(session)
    ScoreStage(RULESET, definition=DEFINITION).run(session, run_id=None)
    original = session.query(Score).filter_by(business_id=b.id).one()
    original_pain = original.pain_score

    tuned = copy.deepcopy(DEFINITION)
    for rule in tuned["pain_rules"]:
        if rule["id"] == "closed_weekends":
            rule["points"] = 40
    b.status = BusinessStatus.SIGNALS_EXTRACTED
    session.commit()

    with pytest.raises(RulesetVersionConflict) as exc:
        ScoreStage(load_ruleset(tuned), definition=tuned).run(session, run_id=None)
    assert "hvac_v1" in str(exc.value)
    assert "version" in str(exc.value).lower()

    # And nothing was overwritten: the conflict is raised before a single
    # Score row is touched.
    assert session.query(Score).filter_by(
        business_id=b.id).one().pain_score == original_pain
