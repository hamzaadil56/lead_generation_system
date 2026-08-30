import csv
from pathlib import Path

from app.clients.fakes import FakeSearchProvider, FakeWebScraper
from app.models.business import Business, BusinessStatus
from app.models.derived import Score
from app.pipeline.discover import DiscoverStage
from app.pipeline.extract_signals import ExtractSignalsStage
from app.pipeline.score import ScoreStage
from app.pipeline.scrape_site import ScrapeSiteStage
from app.services.export import export_leads
from app.services.rulesets import read_ruleset_file
from app.services.search_plan import SearchPlan

PLAN = SearchPlan(vertical="hvac", search_terms=["hvac contractor"],
                  locations=["Houston, TX"], pages_per_query=1)
RULESET = read_ruleset_file(Path("config/rulesets/hvac_v1.yaml"))


def test_full_pipeline_produces_scored_leads_and_a_csv(session, tmp_path):
    DiscoverStage(FakeSearchProvider()).discover(session, None, PLAN)
    ScrapeSiteStage(FakeWebScraper(), per_segment=5).run(session, None)
    ExtractSignalsStage().run(session, None)
    ScoreStage(RULESET).run(session, None)

    scored = session.query(Business).filter_by(status=BusinessStatus.SCORED).all()
    assert len(scored) > 0
    assert session.query(Score).count() == len(scored)

    out = tmp_path / "leads.csv"
    count = export_leads(session, quadrant=None, min_fit=0, path=out)
    assert count == len(scored)

    rows = list(csv.DictReader(out.open()))
    assert {"name", "phone", "website", "segment", "fit_score",
            "pain_score", "quadrant", "coverage", "top_reasons"} <= set(rows[0])
    # Invalid phones must never appear as if they were phone numbers.
    assert all(r["phone"] == "" or r["phone"].startswith("+1") for r in rows)


def test_pipeline_is_idempotent_when_rerun(session):
    for _ in range(2):
        DiscoverStage(FakeSearchProvider()).discover(session, None, PLAN)
        ScrapeSiteStage(FakeWebScraper(), per_segment=5).run(session, None)
        ExtractSignalsStage().run(session, None)
        ScoreStage(RULESET).run(session, None)

    cids = [b.cid for b in session.query(Business).all()]
    assert len(cids) == len(set(cids))
