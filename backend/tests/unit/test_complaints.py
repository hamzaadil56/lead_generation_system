from app.domain.extractors.complaints import count_missed_call_complaints


def test_matches_real_missed_call_phrasings():
    count, quotes = count_missed_call_complaints([
        "Called 3 times, no answer, went with someone else",
        "Left two voicemails over a week, never heard back",
        "Nobody answered the phone after hours",
        "Great service, technician was on time",       # not a complaint
    ])
    assert count == 3
    assert len(quotes) == 3
    assert "Called 3 times" in quotes[0]


def test_no_complaints_returns_zero_and_empty_quotes():
    assert count_missed_call_complaints(["Excellent work"]) == (0, [])
