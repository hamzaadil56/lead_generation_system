from app.models.business import Business, BusinessStatus, Segment
from app.models.derived import Score


def test_business_cid_is_unique(session):
    session.add(Business(cid="123", name="A", status=BusinessStatus.DISCOVERED))
    session.commit()
    # ON CONFLICT DO NOTHING is the dedupe mechanism (ADR-013); a plain
    # second insert must raise so the mechanism is provably needed.
    import sqlalchemy.exc, pytest
    session.add(Business(cid="123", name="B", status=BusinessStatus.DISCOVERED))
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        session.commit()


def test_score_is_keyed_on_business_and_ruleset_version(session):
    b = Business(cid="c1", name="A", status=BusinessStatus.SCORED)
    session.add(b)
    session.commit()
    session.add(Score(business_id=b.id, ruleset_version="hvac_v1",
                      fit_score=70, pain_score=60, quadrant="go_now", coverage=1.0,
                      reasons=[]))
    session.add(Score(business_id=b.id, ruleset_version="hvac_v2",
                      fit_score=80, pain_score=55, quadrant="nurture", coverage=1.0,
                      reasons=[]))
    session.commit()
    assert session.query(Score).count() == 2  # both versions coexist (ADR-005)
