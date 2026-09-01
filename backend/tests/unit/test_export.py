import csv
from pathlib import Path

from app.models.business import Business, BusinessStatus
from app.models.derived import Score
from app.services.export import export_leads


def _scored_business(session, cid: str, name: str) -> Business:
    b = Business(cid=cid, name=name, status=BusinessStatus.SCORED,
                phone_is_valid=False)
    session.add(b)
    session.flush()
    session.add(Score(business_id=b.id, ruleset_version="hvac_v1",
                      fit_score=80, pain_score=80, quadrant="go_now",
                      coverage=0.9, reasons=[]))
    session.commit()
    return b


def test_export_round_trips_non_ascii_business_names(session, tmp_path):
    """Finding 3: exporting a business whose name contains non-ASCII
    characters must round-trip intact when the file is read back as
    UTF-8."""
    _scored_business(session, "c1", "Café HVAC & Muñoz A/C")

    out = tmp_path / "leads.csv"
    count = export_leads(session, quadrant=None, min_fit=0, path=out)
    assert count == 1

    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert rows[0]["name"] == "Café HVAC & Muñoz A/C"


def test_export_opens_the_csv_with_explicit_utf8_encoding(session, tmp_path, monkeypatch):
    """Pins the actual defect: `path.open("w", newline="")` with no
    `encoding=` inherits the platform's locale encoding, which raises
    UnicodeEncodeError mid-write on a non-UTF-8 locale (e.g. Windows).
    Spies on Path.open to assert the export path always passes
    encoding="utf-8" explicitly, regardless of host locale. Fails on the
    unfixed code, whose call to path.open("w", newline="") carries no
    encoding kwarg at all."""
    _scored_business(session, "c1", "Café HVAC")
    out = tmp_path / "leads.csv"

    captured: dict[str, object] = {}
    real_open = Path.open

    def spy_open(self, *args, **kwargs):
        if self == out:
            captured["args"] = args
            captured["kwargs"] = kwargs
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", spy_open)

    export_leads(session, quadrant=None, min_fit=0, path=out)

    assert captured.get("kwargs", {}).get("encoding") == "utf-8", (
        "export_leads must open the CSV with an explicit encoding='utf-8', "
        f"got args={captured.get('args')} kwargs={captured.get('kwargs')}"
    )


def test_export_is_parameterised_by_ruleset_version(session, tmp_path):
    """Deferred item 17: `ruleset_version` was hardcoded to "hvac_v1" and
    not threaded from the CLI, so a second vertical exported 0 rows — a
    failure that looks like "no leads matched" rather than a bug."""
    b = Business(cid="c1", name="Plumbing Co", status=BusinessStatus.SCORED,
                 phone_is_valid=False)
    session.add(b)
    session.flush()
    session.add(Score(business_id=b.id, ruleset_version="plumbing_v1",
                      fit_score=80, pain_score=80, quadrant="go_now",
                      coverage=0.9, reasons=[]))
    session.commit()

    out = tmp_path / "leads.csv"
    assert export_leads(session, None, 0, out) == 0            # hvac_v1 default
    assert export_leads(session, None, 0, out,
                        ruleset_version="plumbing_v1") == 1


def test_export_honours_the_filters_added_for_the_dashboard(session, tmp_path):
    """`export_leads` took quadrant/min_fit/ruleset_version only, so the
    dashboard's Export CSV shipped the whole table under a URL that claimed
    to be filtered. These four are the rest of what `GET /leads` accepts."""
    from app.models.manual import Outcome

    tx = Business(cid="c1", name="TX Air", state="TX", vertical="hvac",
                  status=BusinessStatus.SCORED, phone_is_valid=False)
    ca = Business(cid="c2", name="CA Air", state="CA", vertical="plumbing",
                  status=BusinessStatus.SCORED, phone_is_valid=False)
    session.add_all([tx, ca])
    session.flush()
    for b, pain in ((tx, 80), (ca, 10)):
        session.add(Score(business_id=b.id, ruleset_version="hvac_v1",
                          fit_score=80, pain_score=pain, quadrant="go_now",
                          coverage=0.9, reasons=[]))
    session.add(Outcome(business_id=tx.id, status="contacted", source="manual"))
    session.commit()

    out = tmp_path / "leads.csv"
    assert export_leads(session, None, 0, out) == 2                  # unfiltered
    assert export_leads(session, None, 0, out, state="CA") == 1
    assert export_leads(session, None, 0, out, min_pain=50) == 1
    assert export_leads(session, None, 0, out, vertical="plumbing") == 1
    assert export_leads(session, None, 0, out,
                        outcome_status="contacted") == 1
    assert export_leads(session, None, 0, out, outcome_status="won") == 0
    # And the names really are the filtered ones, not just the right count.
    export_leads(session, None, 0, out, state="CA")
    assert [r["name"] for r in csv.DictReader(out.open(encoding="utf-8"))] \
        == ["CA Air"]
