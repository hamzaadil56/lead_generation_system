from app.domain.hours import parse_opening_hours

ALL_DAY = {d: "Open 24 hours" for d in
           ["Monday", "Tuesday", "Wednesday", "Thursday",
            "Friday", "Saturday", "Sunday"]}


def test_open_24_hours_every_day():
    h = parse_opening_hours(ALL_DAY)            # real: Air Tech of Houston
    assert h.is_24_7 is True
    assert h.closes_before_6pm is False
    assert h.closed_weekends is False


def test_weekday_business_hours_closed_weekends():
    # real: Royal Air Houston, 8,758 reviews — the lead ADR-022 was written about
    h = parse_opening_hours({
        "Monday": "8 AM–5 PM", "Tuesday": "8 AM–5 PM", "Wednesday": "8 AM–5 PM",
        "Thursday": "8 AM–5 PM", "Friday": "8 AM–5 PM",
        "Saturday": "Closed", "Sunday": "Closed",
    })
    assert h.is_24_7 is False
    assert h.closes_before_6pm is True
    assert h.closed_weekends is True


def test_saturday_open_is_not_closed_weekends():
    # real: All American AC — Sat 8-12, Sun closed
    h = parse_opening_hours({
        **{d: "8 AM–6 PM" for d in ["Monday", "Tuesday", "Wednesday",
                                     "Thursday", "Friday"]},
        "Saturday": "8 AM–12 PM", "Sunday": "Closed",
    })
    assert h.closed_weekends is False
    assert h.closes_before_6pm is False          # 6 PM is not *before* 6 PM


def test_malformed_day_sets_parse_failed_and_is_not_guessed():
    # real defect: Ethan Clark returned "8 AM–5 AM" for Thursday (ADR-021)
    h = parse_opening_hours({
        "Monday": "8 AM–5 PM", "Tuesday": "8 AM–5 PM", "Wednesday": "8 AM–5 PM",
        "Thursday": "8 AM–5 AM", "Friday": "8 AM–5 PM",
        "Saturday": "8 AM–12 PM", "Sunday": "Closed",
    })
    assert h.parse_failed is True
    assert h.closes_before_6pm is True           # the four valid days still count


def test_missing_hours_returns_all_unknown():
    h = parse_opening_hours(None)
    assert h.parse_failed is True
    assert h.is_24_7 is False
