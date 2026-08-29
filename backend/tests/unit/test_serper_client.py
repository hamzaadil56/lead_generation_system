import json
from pathlib import Path
from app.clients.serper import parse_search_response

RAW = json.loads(
    Path("tests/fixtures/serper_maps_houston_hvac.json").read_text()
)


def test_parses_all_records_and_reports_credits():
    result = parse_search_response(RAW)
    assert len(result.records) == 20
    assert result.credits == 3          # self-reported actual cost (ADR-021)


def test_maps_every_field_from_a_real_record():
    r = parse_search_response(RAW).records[0]
    assert r.title == "Air Tech of Houston AC & Plumbing"
    assert r.cid == "16433610908791049931"
    assert r.place_id == "ChIJnepQB1XGQIYRy455cw3qD-Q"
    assert r.rating_count == 6445
    assert r.opening_hours["Monday"] == "Open 24 hours"
    assert r.booking_links[0].startswith("https://book.servicetitan.com/")
    assert r.raw is not None             # full payload retained (ADR-003)


def test_missing_address_is_none_not_an_error():
    """Service-area businesses have no storefront (ADR-021)."""
    records = parse_search_response(RAW).records
    richmonds = next(r for r in records if r.title == "Richmonds Air")
    assert richmonds.address is None


def test_absent_booking_links_is_none_not_empty_list():
    """Absence IS the phone-only signal and must survive parsing."""
    records = parse_search_response(RAW).records
    htown = next(r for r in records
                 if r.title == "H-Town AC Repair HVAC services Houston")
    assert htown.booking_links is None
