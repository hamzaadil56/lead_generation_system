from datetime import datetime, timedelta

from app.models.run import SearchQuery
from app.services.preview import preview_search_plan

VERTICALS = {"hvac": {"search_terms": ["hvac contractor", "ac repair"],
                      "ruleset": "hvac_v1"}}
LOCATIONS = {"TX": {"metros": ["Houston, TX", "Dallas, TX", "Austin, TX"]}}


def test_preview_expands_terms_times_locations(session):
    p = preview_search_plan(session, "hvac", "TX", None, 5,
                            VERTICALS, LOCATIONS)

    assert p.search_count == 6            # 2 terms x 3 metros
    assert len(p.queries) == 6
    assert "hvac contractor in Houston, TX" in p.queries


def test_preview_estimates_cost_from_the_serper_price(session):
    """Serper bills per search; the estimate must move with page count, or a
    user cannot tell a $0.03 run from a $0.30 one."""
    cheap = preview_search_plan(session, "hvac", None, "Houston, TX", 1,
                                VERTICALS, LOCATIONS)
    dear = preview_search_plan(session, "hvac", None, "Houston, TX", 10,
                               VERTICALS, LOCATIONS)

    assert dear.estimated_cost_usd > cheap.estimated_cost_usd
    assert cheap.estimated_cost_usd > 0


def test_preview_estimates_results_from_pages(session):
    p = preview_search_plan(session, "hvac", None, "Houston, TX", 2,
                            VERTICALS, LOCATIONS)
    # 2 terms x 1 location x 2 pages x 20 results per page
    assert p.estimated_results == 80


def test_preview_flags_queries_run_in_the_last_30_days(session):
    session.add(SearchQuery(term="hvac contractor", location="Houston, TX",
                            executed_at=datetime.utcnow() - timedelta(days=3),
                            result_count=20))
    session.commit()

    p = preview_search_plan(session, "hvac", None, "Houston, TX", 1,
                            VERTICALS, LOCATIONS)

    assert p.recently_run_queries == ["hvac contractor in Houston, TX"]


def test_preview_does_not_flag_an_old_query(session):
    session.add(SearchQuery(term="hvac contractor", location="Houston, TX",
                            executed_at=datetime.utcnow() - timedelta(days=90),
                            result_count=20))
    session.commit()

    p = preview_search_plan(session, "hvac", None, "Houston, TX", 1,
                            VERTICALS, LOCATIONS)

    assert p.recently_run_queries == []


def test_preview_spends_nothing(session):
    """The confirm screen must not call a provider. If this ever fails, the
    preview has started costing money."""
    from app.models.derived import ApiCall
    before = session.query(ApiCall).count()

    preview_search_plan(session, "hvac", "TX", None, 5, VERTICALS, LOCATIONS)

    assert session.query(ApiCall).count() == before
