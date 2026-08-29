from app.models.business import Business, BusinessStatus
from app.models.derived import Signals
from app.models.manual import ManualFacts
from app.pipeline.extract_signals import ExtractSignalsStage


def test_manual_facts_override_derived_values(session):
    """ADR-008: signals is rebuildable, manual_facts is not. Manual wins."""
    b = Business(cid="c1", name="A", status=BusinessStatus.SITE_SCRAPED,
                 opening_hours={"Monday": "8 AM–5 PM"}, booking_links=None)
    session.add(b)
    session.flush()
    session.add(ManualFacts(business_id=b.id, estimated_employees=22,
                            has_office_admin=True))
    session.commit()

    ExtractSignalsStage().run(session, run_id=None)

    sig = session.query(Signals).filter_by(business_id=b.id).one()
    assert sig.estimated_employees == 22
    assert sig.employee_est_source == "manual_apollo"
    assert b.status is BusinessStatus.SIGNALS_EXTRACTED


def test_rerunning_the_stage_does_not_wipe_manual_facts(session):
    b = Business(cid="c2", name="B", status=BusinessStatus.SITE_SCRAPED)
    session.add(b); session.flush()
    session.add(ManualFacts(business_id=b.id, estimated_employees=15))
    session.commit()

    ExtractSignalsStage().run(session, run_id=None)
    b.status = BusinessStatus.SITE_SCRAPED       # simulate the enrichment loop
    session.commit()
    ExtractSignalsStage().run(session, run_id=None)

    assert session.query(Signals).filter_by(
        business_id=b.id).one().estimated_employees == 15
