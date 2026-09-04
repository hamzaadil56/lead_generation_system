import csv
import itertools
import os
import sys
from datetime import datetime
from pathlib import Path

os.environ.setdefault("DATABASE_URL",
                      "postgresql+psycopg://postgres:dev@localhost:5432/leadgen_test")
os.environ.setdefault("SERPER_KEY", "test-serper-key")
os.environ.setdefault("FIRECRAWL_KEY", "test-firecrawl-key")

# `cli.py` is a top-level script module living at the backend/ repo root, not
# part of the installed `leadgen` package, so it is only importable once that
# directory is on sys.path -- see tests/integration/test_cli.py for the same
# arrangement.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import cli  # noqa: E402
from app.models.business import Business, BusinessStatus  # noqa: E402
from app.models.derived import Score  # noqa: E402
from app.models.manual import Contact, Suppression  # noqa: E402
from app.repositories.leads import LeadFilters  # noqa: E402
from app.services.contact_export import export_contacts  # noqa: E402

_CID_SEQ = itertools.count(1)


def _business(session, website="https://leisuration.test",
             name="Leisuration Air", vertical="hvac",
             city="Austin", state="TX"):
    cid = f"export-{next(_CID_SEQ)}"
    b = Business(cid=cid, name=name, website=website, vertical=vertical,
                city=city, state=state, status=BusinessStatus.SCORED)
    session.add(b)
    session.flush()
    return b


def _scored_business(session, cid_hint=None, *, quadrant, fit=80, pain=70,
                     **kwargs):
    business = _business(session, **kwargs)
    session.add(Score(business_id=business.id, ruleset_version="hvac_v1",
                      fit_score=fit, pain_score=pain, quadrant=quadrant,
                      coverage=0.8, reasons=[]))
    session.commit()
    return business


def test_the_export_emits_only_confirmed_unsuppressed_addressed_contacts(
        session, tmp_path):
    """Four contacts on one filtered lead; exactly one may leave the system."""
    business = _scored_business(session, "c-1", quadrant="go_now")
    session.add_all([
        Contact(business_id=business.id, email="good@acme.test",
                name="John", source="manual",
                confirmed_at=datetime(2026, 9, 1)),
        Contact(business_id=business.id, email="unconfirmed@acme.test",
                source="website", confidence=0.9, confirmed_at=None),
        Contact(business_id=business.id, email="gone@acme.test",
                source="manual", confirmed_at=datetime(2026, 9, 1)),
        Contact(business_id=business.id, name="No Address Yet",
                source="manual", confirmed_at=datetime(2026, 9, 1)),
    ])
    session.add(Suppression(email="gone@acme.test", reason="unsubscribed",
                            source="manual", created_at=datetime(2026, 9, 1)))
    session.commit()

    path = tmp_path / "contacts.csv"
    count = export_contacts(session, LeadFilters(), path)

    rows = list(csv.DictReader(path.open()))
    assert count == 1
    assert [r["email"] for r in rows] == ["good@acme.test"]


def test_the_export_carries_the_business_columns_for_mail_merge(session, tmp_path):
    business = _scored_business(session, quadrant="go_now", fit=90, pain=80,
                                name="Leisuration Air",
                                website="https://leisuration.test",
                                city="Austin", state="TX")
    session.add(Contact(business_id=business.id, email="owner@leisuration.test",
                        name="Jane", role="Owner", source="manual",
                        confirmed_at=datetime(2026, 9, 1)))
    session.commit()

    path = tmp_path / "contacts.csv"
    export_contacts(session, LeadFilters(), path)

    rows = list(csv.DictReader(path.open()))
    assert len(rows) == 1
    row = rows[0]
    assert row["business_name"] == "Leisuration Air"
    assert row["city"] == "Austin"
    assert row["state"] == "TX"
    assert row["website"] == "https://leisuration.test"
    assert row["fit_score"] == "90"
    assert row["pain_score"] == "80"
    assert row["quadrant"] == "go_now"
    # segment is unset in this test's fixture, but the column must still be
    # present so a mail-merge tool never chokes on a missing header.
    assert "segment" in row


def test_one_row_per_contact_not_per_business(session, tmp_path):
    business = _scored_business(session, quadrant="go_now")
    session.add_all([
        Contact(business_id=business.id, email="a@acme.test", source="manual",
                confirmed_at=datetime(2026, 9, 1)),
        Contact(business_id=business.id, email="b@acme.test", source="manual",
                confirmed_at=datetime(2026, 9, 1)),
    ])
    session.commit()

    path = tmp_path / "contacts.csv"
    count = export_contacts(session, LeadFilters(), path)

    rows = list(csv.DictReader(path.open()))
    assert count == 2
    assert {r["email"] for r in rows} == {"a@acme.test", "b@acme.test"}


def test_the_export_honours_the_lead_filters(session, tmp_path):
    go_now = _scored_business(session, quadrant="go_now",
                              website="https://gonow.test")
    cold = _scored_business(session, quadrant="cold", fit=10, pain=10,
                            website="https://coldbiz.test")
    session.add_all([
        Contact(business_id=go_now.id, email="owner@gonow.test",
                source="manual", confirmed_at=datetime(2026, 9, 1)),
        Contact(business_id=cold.id, email="owner@coldbiz.test",
                source="manual", confirmed_at=datetime(2026, 9, 1)),
    ])
    session.commit()

    path = tmp_path / "contacts.csv"
    count = export_contacts(session, LeadFilters(quadrant="go_now"), path)

    rows = list(csv.DictReader(path.open()))
    assert count == 1
    assert [r["email"] for r in rows] == ["owner@gonow.test"]


def test_the_best_leads_come_first(session, tmp_path):
    hot = _scored_business(session, quadrant="go_now", fit=90, pain=90,
                           website="https://hot.test")
    warm = _scored_business(session, quadrant="go_now", fit=50, pain=50,
                            website="https://warm.test")
    session.add_all([
        Contact(business_id=warm.id, email="owner@warm.test", source="manual",
                confirmed_at=datetime(2026, 9, 1)),
        Contact(business_id=hot.id, email="owner@hot.test", source="manual",
                confirmed_at=datetime(2026, 9, 1)),
    ])
    session.commit()

    path = tmp_path / "contacts.csv"
    export_contacts(session, LeadFilters(), path)

    rows = list(csv.DictReader(path.open()))
    assert [r["email"] for r in rows] == ["owner@hot.test", "owner@warm.test"]


def test_the_suppress_command_normalises_before_storing(session):
    """The export's join is a plain equality, which is only safe because BOTH
    sides are stored normalised. Nothing makes the join case-insensitive, so
    the normalisation has to happen on the way in -- test that, not the join.
    Invoke the CLI command with a mixed-case address and assert the stored
    primary key is lowercased."""
    from typer.testing import CliRunner

    runner = CliRunner()

    class _FakeSessionCtx:
        def __enter__(self_inner):
            return session

        def __exit__(self_inner, *exc):
            return False

    original_get_session = cli.get_session
    cli.get_session = lambda: _FakeSessionCtx()
    try:
        result = runner.invoke(
            cli.app, ["suppress", "  Gone@ACME.test  ", "--reason", "bounced"])
    finally:
        cli.get_session = original_get_session

    assert result.exit_code == 0, result.output
    row = session.get(Suppression, "gone@acme.test")
    assert row is not None
    assert row.reason == "bounced"
