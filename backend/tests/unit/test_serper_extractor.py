from app.domain.extractors.serper import extract_serper_signals


def test_royal_air_signals():
    s = extract_serper_signals(
        opening_hours={**{d: "8 AM–5 PM" for d in
                          ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]},
                       "Saturday": "Closed", "Sunday": "Closed"},
        booking_links=["http://www.royalairhouston.com/appointment-service-request/"],
        segment="enterprise",
    )
    assert s["closed_weekends"] is True
    assert s["closes_before_6pm"] is True
    assert s["is_24_7"] is False
    assert s["booking_vendor"] == "own"
    assert s["has_booking_link"] is True
    assert s["is_phone_only"] is False


def test_phone_only_business_has_no_booking_link_key():
    s = extract_serper_signals(opening_hours=None, booking_links=None,
                               segment="emerging")
    assert s["is_phone_only"] is True
    assert s["has_booking_link"] is False
    assert s["hours_parse_failed"] is True
