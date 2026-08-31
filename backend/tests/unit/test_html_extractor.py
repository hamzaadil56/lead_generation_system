from pathlib import Path
import pytest
from app.domain.extractors.html import extract_html_signals

FIX = Path("tests/fixtures")


def _load(name: str) -> str:
    return (FIX / f"hvac_site_{name}.html").read_text()


@pytest.mark.parametrize("site,vendor", [
    ("uptown", "housecallpro"),      # chat.housecallpro.com
    ("mission", "scheduleengine"),   # webchat.scheduleengine.net
    ("revair", "purechat"),          # app.purechat.com
])
def test_detects_real_chat_vendors(site, vendor):
    s = extract_html_signals(_load(site), None)
    assert s["has_chat_widget"] is True
    assert s["chat_vendor"] == vendor


def test_site_without_chat_reports_none():
    s = extract_html_signals(_load("royalair"), None)
    assert s["has_chat_widget"] is False
    assert s["chat_vendor"] is None


@pytest.mark.parametrize("junk", [
    "--wp--preset--shadow--crisp: 6px 6px 0px rgb(0,0,0)",   # WordPress CSS
    ".swiper-scrollbar-drag{height:100%}",                    # Swiper CSS
    'widgetUrl":"https:\\/\\/engage.wixapps.net\\/chat-widget-server\\/x"',
])
def test_known_false_positives_stay_excluded(junk):
    """Each of these matched a guessed fingerprint on real sites. If one ever
    trips has_chat_widget again, the pain track is silently corrupted."""
    assert extract_html_signals(junk, None)["has_chat_widget"] is False


def test_detects_google_ads_from_a_real_page():
    assert extract_html_signals(_load("uptown"), None)["runs_google_ads"] is True


def test_ga4_analytics_alone_is_not_google_ads():
    """G- is analytics; AW- is Ads. 5 of 20 real sites had G- and no ads."""
    html = '<script src="https://www.googletagmanager.com/gtag/js?id=G-ABC123"></script>'
    assert extract_html_signals(html, None)["runs_google_ads"] is False


def test_detects_meta_pixel_from_a_real_page():
    assert extract_html_signals(_load("revair"), None)["has_meta_pixel"] is True


def test_detects_contact_form_on_real_pages():
    assert extract_html_signals(_load("royalair"), None)["has_contact_form"] is True


def test_html_catches_software_that_booking_links_missed():
    """House Pro's Serper bookingLinks pointed only at its own site, but the
    page embeds ServiceTitan. HTML adds ~10% coverage over bookingLinks."""
    html = '<script src="https://embed.scheduler.servicetitan.com/x.js"></script>'
    assert extract_html_signals(html, None)["software_from_html"] == "servicetitan"


def test_no_html_returns_the_keys_ABSENT_not_false():
    """C3. This test previously asserted the defect as correct:

        assert s["has_chat_widget"] is False
        assert s["runs_google_ads"] is False

    Those were coerced booleans over an empty string, not findings. The
    engine treats a present `False` as evidence, so a dead-site business
    matched `no_chat_widget` for +20 pain points on nothing and kept
    `runs_google_ads` in the fit denominator. `on_missing: skip` can only
    work if an unevaluated signal is ABSENT.
    """
    s = extract_html_signals(None, None)
    assert s == {}
    for key in ("has_chat_widget", "runs_google_ads", "has_contact_form",
                "claims_24_7", "software_from_html", "chat_vendor",
                "has_meta_pixel"):
        assert key not in s


def test_a_signal_evaluated_against_real_html_and_not_found_stays_false():
    """The other half of the distinction: absence of evidence in HTML we
    DID read is a finding, and must not regress to 'unknown'."""
    s = extract_html_signals(_load("royalair"), None)
    assert s["has_chat_widget"] is False
    assert "has_chat_widget" in s


def test_markdown_only_input_knows_claims_24_7_and_nothing_else():
    s = extract_html_signals(None, "We are open 24/7 for emergencies")
    assert s == {"claims_24_7": True}
