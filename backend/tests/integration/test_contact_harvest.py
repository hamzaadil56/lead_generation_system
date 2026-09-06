import itertools
from datetime import datetime

from app.models.business import Business, BusinessStatus
from app.models.derived import RawPayload, Score
from app.models.manual import Contact
from app.repositories.leads import LeadFilters
from app.services.contact_harvest import harvest_for_business, harvest_for_filters

_HTML = """
<html><body>
  <a href="mailto:owner@leisuration.test">Email the owner</a>
  <p>Billing: accounts@leisuration.test</p>
  <p>noreply@leisuration.test</p>
</body></html>
"""

_CID_SEQ = itertools.count(1)


def _business(session, website="https://leisuration.test",
             name="Leisuration Air", vertical="hvac"):
    cid = f"harvest-{next(_CID_SEQ)}"
    b = Business(cid=cid, name=name, website=website, vertical=vertical,
                status=BusinessStatus.SCORED)
    session.add(b)
    session.flush()
    return b


def _scored_business(session, *, quadrant, fit=80, pain=70, **kwargs):
    business = _business(session, **kwargs)
    session.add(Score(business_id=business.id, ruleset_version="hvac_v1",
                      fit_score=fit, pain_score=pain, quadrant=quadrant,
                      coverage=0.8, reasons=[]))
    session.commit()
    return business


def _payload(session, business_id, html, url="https://leisuration.test/contact"):
    session.add(RawPayload(business_id=business_id, source="firecrawl",
                           url=url, fetched_at=datetime(2026, 9, 1),
                           payload={}, raw_text=html))
    session.flush()


def test_harvest_creates_one_contact_per_usable_address(session):
    business = _business(session, website="https://leisuration.test")
    _payload(session, business.id, _HTML)

    result = harvest_for_business(session, business.id)

    assert result.created == 2          # noreply is rejected
    emails = {c.email for c in session.query(Contact).all()}
    assert emails == {"owner@leisuration.test", "accounts@leisuration.test"}


def test_harvested_contacts_are_unconfirmed_and_carry_their_reason(session):
    business = _business(session, website="https://leisuration.test")
    _payload(session, business.id, _HTML)
    harvest_for_business(session, business.id)

    row = session.query(Contact).filter_by(
        email="owner@leisuration.test").one()
    assert row.confirmed_at is None     # only a human sets this
    assert row.source == "website"
    assert row.confidence == 0.9
    assert row.discovery_note
    assert row.role is None             # never guessed
    assert row.is_primary is False


def test_harvesting_twice_creates_nothing_the_second_time(session):
    """The unique constraint is the guard, but the service must not rely on
    hitting it -- an IntegrityError would abort the whole transaction."""
    business = _business(session, website="https://leisuration.test")
    _payload(session, business.id, _HTML)

    first = harvest_for_business(session, business.id)
    second = harvest_for_business(session, business.id)

    assert first.created == 2
    assert second.created == 0
    assert second.skipped == 2
    assert session.query(Contact).count() == 2


def test_the_same_address_on_four_pages_inserts_once(session):
    """A footer address appears on every allowlisted page. Deduplicating only
    within a page would put two inserts of it in one transaction, raise
    IntegrityError against uq_contacts_business_email, and abort the whole
    harvest."""
    business = _business(session, website="https://leisuration.test")
    for page in ("about", "contact", "services", "team"):
        _payload(session, business.id,
                 '<a href="mailto:owner@leisuration.test">x</a>',
                 url=f"https://leisuration.test/{page}")

    result = harvest_for_business(session, business.id)

    assert result.created == 1
    assert session.query(Contact).count() == 1


def test_harvest_reads_every_page_not_only_the_newest(session):
    """/contact and /team are exactly the pages that carry addresses."""
    business = _business(session, website="https://leisuration.test")
    _payload(session, business.id, "<p>a@leisuration.test</p>",
             url="https://leisuration.test/about")
    _payload(session, business.id, "<p>b@leisuration.test</p>",
             url="https://leisuration.test/team")

    assert harvest_for_business(session, business.id).created == 2


def test_harvest_never_overwrites_what_a_human_edited(session):
    business = _business(session, website="https://leisuration.test")
    _payload(session, business.id, _HTML)
    harvest_for_business(session, business.id)

    row = session.query(Contact).filter_by(
        email="owner@leisuration.test").one()
    row.name = "John Smith"
    row.role = "Owner"
    row.confirmed_at = datetime(2026, 9, 2)
    session.commit()

    harvest_for_business(session, business.id)

    row = session.query(Contact).filter_by(
        email="owner@leisuration.test").one()
    assert row.name == "John Smith"
    assert row.role == "Owner"
    assert row.confirmed_at == datetime(2026, 9, 2)


def test_harvest_never_deletes_a_contact(session):
    business = _business(session, website="https://leisuration.test")
    session.add(Contact(business_id=business.id, email="typed@elsewhere.test",
                        source="manual", confirmed_at=datetime(2026, 9, 1)))
    session.commit()
    _payload(session, business.id, _HTML)

    harvest_for_business(session, business.id)

    assert session.query(Contact).filter_by(
        email="typed@elsewhere.test").count() == 1


def test_a_business_with_no_scraped_html_returns_zero_not_an_error(session):
    """Absent data is a result, not a failure -- the same distinction the
    pipeline draws with BusinessPermanentError."""
    business = _business(session, website="https://leisuration.test")
    assert harvest_for_business(session, business.id).created == 0


def test_non_firecrawl_payloads_are_ignored(session):
    """Serper and SerpApi payloads are JSON, not page HTML."""
    business = _business(session, website="https://leisuration.test")
    session.add(RawPayload(business_id=business.id, source="serper_maps",
                           url=None, fetched_at=datetime(2026, 9, 1),
                           payload={"email": "x@leisuration.test"},
                           raw_text="<p>x@leisuration.test</p>"))
    session.flush()

    assert harvest_for_business(session, business.id).created == 0


def test_an_unknown_business_id_returns_zero(session):
    assert harvest_for_business(session, 999999).created == 0


def test_harvest_for_filters_covers_the_filtered_set(session):
    """Bulk harvest is built on `filtered_leads` -- the same predicate the
    leads list and export use. A `go_now` business with a cached page must
    gain contacts; a `cold` business in the same run must not, because it
    falls outside the filter."""
    go_now = _scored_business(session, quadrant="go_now",
                              website="https://leisuration.test")
    cold = _scored_business(session, quadrant="cold", fit=10, pain=10,
                            website="https://coldbiz.test")
    _payload(session, go_now.id, "<p>owner@leisuration.test</p>")
    _payload(session, cold.id, "<p>owner@coldbiz.test</p>")

    result = harvest_for_filters(session, LeadFilters(quadrant="go_now"))

    assert result.businesses == 1
    assert result.created == 1
    assert session.query(Contact).filter_by(business_id=go_now.id).count() == 1
    assert session.query(Contact).filter_by(business_id=cold.id).count() == 0
