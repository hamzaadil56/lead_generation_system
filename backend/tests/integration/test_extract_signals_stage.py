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


def _dead_site_business(session, cid: str) -> Business:
    from datetime import datetime
    from app.models.derived import RawPayload
    b = Business(cid=cid, name=cid, status=BusinessStatus.SITE_SCRAPED,
                 website="https://gone.example",
                 opening_hours={"Monday": "8 AM–5 PM", "Saturday": "Closed",
                                "Sunday": "Closed"},
                 booking_links=["https://gone.example/book"])
    session.add(b); session.flush()
    session.add(RawPayload(business_id=b.id, source="firecrawl",
                           url=b.website,
                           payload={"url": b.website, "status": "dead",
                                    "markdown": None, "raw_html": None,
                                    "links": [], "raw": {}},
                           raw_text=None, fetched_at=datetime.utcnow()))
    session.commit()
    return b


def _scraped_business(session, cid: str) -> Business:
    from datetime import datetime
    from app.models.derived import RawPayload
    html = "<html><body><p>we fix air conditioners</p></body></html>"
    b = Business(cid=cid, name=cid, status=BusinessStatus.SITE_SCRAPED,
                 website="https://alive.example",
                 opening_hours={"Monday": "8 AM–5 PM", "Saturday": "Closed",
                                "Sunday": "Closed"},
                 booking_links=["https://alive.example/book"])
    session.add(b); session.flush()
    session.add(RawPayload(business_id=b.id, source="firecrawl",
                           url=b.website,
                           payload={"url": b.website, "status": "ok",
                                    "markdown": "we fix air conditioners",
                                    "raw_html": html, "links": [], "raw": {}},
                           raw_text=html, fetched_at=datetime.utcnow()))
    session.commit()
    return b


def test_dead_site_leaves_html_signals_unknown_not_false(session):
    """C3 at the stage boundary. `extract_html_signals(None, None)` used to
    return has_chat_widget=False / runs_google_ads=False as positive facts,
    which the rules engine then scored as evidence."""
    b = _dead_site_business(session, "dead1")
    ExtractSignalsStage().run(session, run_id=None)

    sig = session.query(Signals).filter_by(business_id=b.id).one()
    assert sig.website_status == "dead"
    assert sig.has_chat_widget is None
    assert sig.runs_google_ads is None
    assert sig.has_contact_form is None
    assert sig.claims_24_7 is None


def test_dead_site_scores_materially_lower_coverage_than_a_scraped_site(session):
    """ADR-020's load-bearing claim: coverage is what distinguishes the
    tiers. Before the fix both businesses scored coverage 0.7 — a dead site
    was indistinguishable from a fully scraped one — and the dead site
    collected 20 pain points from `no_chat_widget` on zero evidence."""
    from pathlib import Path
    from app.models.derived import Score
    from app.pipeline.score import ScoreStage
    from app.services.rulesets import read_ruleset_file

    dead = _dead_site_business(session, "dead2")
    alive = _scraped_business(session, "alive2")

    ExtractSignalsStage().run(session, run_id=None)
    ScoreStage(read_ruleset_file(
        Path("config/rulesets/hvac_v1.yaml"))).run(session, run_id=None)

    dead_score = session.query(Score).filter_by(business_id=dead.id).one()
    alive_score = session.query(Score).filter_by(business_id=alive.id).one()

    assert dead_score.coverage < alive_score.coverage
    # 5 of 10 rules applicable vs 7 of 10 — not a rounding difference.
    assert alive_score.coverage - dead_score.coverage >= 0.15
    # ADR-014: no_chat_widget must not fire for a site nobody could read.
    dead_rules = {r["rule"] for r in dead_score.reasons}
    assert "no_chat_widget" not in dead_rules
    assert "no_chat_widget" in {r["rule"] for r in alive_score.reasons}


def test_embedded_vendor_scheduler_is_a_fallback_for_booking_vendor(session):
    """I4/ADR-023: `software_from_html` was extracted, stored and tested but
    scored by nothing, so ADR-023's named cases (House Pro embeds
    ServiceTitan, Revolution Air embeds Housecall Pro — both with
    bookingLinks pointing only at their own site) scored 0 on the
    30-point `field_service_software` fit rule and the ~10% detection
    uplift the ADR paid for was never realised.

    ADR-023 calls it a "secondary vendor source", so it is applied as a
    fallback for `booking_vendor` here rather than as a new scoring rule:
    `hvac_v1.yaml` is pinned by five golden tests hand-computed from real
    Houston data."""
    from datetime import datetime
    from app.models.derived import RawPayload
    html = '<script src="https://embed.scheduler.servicetitan.com/x.js"></script>'
    b = Business(cid="housepro", name="House Pro",
                 status=BusinessStatus.SITE_SCRAPED,
                 website="https://housepro.example",
                 booking_links=["https://housepro.example/schedule"])
    session.add(b); session.flush()
    session.add(RawPayload(business_id=b.id, source="firecrawl",
                           url=b.website,
                           payload={"url": b.website, "status": "ok",
                                    "markdown": "book now", "raw_html": html,
                                    "links": [], "raw": {}},
                           raw_text=html, fetched_at=datetime.utcnow()))
    session.commit()

    ExtractSignalsStage().run(session, run_id=None)
    sig = session.query(Signals).filter_by(business_id=b.id).one()
    assert sig.software_from_html == "servicetitan"
    # Without the fallback this stayed "own" and the 30-point rule missed.
    assert sig.booking_vendor == "servicetitan"


def test_a_recognised_booking_vendor_is_not_overwritten_by_html(session):
    from datetime import datetime
    from app.models.derived import RawPayload
    html = '<script src="https://embed.scheduler.servicetitan.com/x.js"></script>'
    b = Business(cid="jobberco", name="Jobber Co",
                 status=BusinessStatus.SITE_SCRAPED,
                 website="https://jobberco.example",
                 booking_links=["https://clienthub.getjobber.com/x"])
    session.add(b); session.flush()
    session.add(RawPayload(business_id=b.id, source="firecrawl",
                           url=b.website,
                           payload={"url": b.website, "status": "ok",
                                    "markdown": "", "raw_html": html,
                                    "links": [], "raw": {}},
                           raw_text=html, fetched_at=datetime.utcnow()))
    session.commit()

    ExtractSignalsStage().run(session, run_id=None)
    sig = session.query(Signals).filter_by(business_id=b.id).one()
    assert sig.booking_vendor == "jobber"
