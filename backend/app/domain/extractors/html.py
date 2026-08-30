import re
from typing import Any

# CONFIRMED against 20 live Houston HVAC sites on 2026-08-29 (ADR-023).
# Every previously-guessed vendor (Podium, Intercom, Drift, Tawk, Tidio)
# scored ZERO hits and was removed. Do not re-add one without evidence.
CHAT_FINGERPRINTS: list[tuple[str, str]] = [
    ("webchat.scheduleengine.net", "scheduleengine"),   # 1/20 sites
    ("app.purechat.com", "purechat"),                   # 1/20
    ("chat.housecallpro.com", "housecallpro"),          # 1/20
]

# Substrings that LOOK like fingerprints and are not. Each was observed
# producing a false positive; the test suite asserts they stay excluded.
#   "crisp"        -> WordPress CSS var --wp--preset--shadow--crisp  (11/20 sites)
#   "rollbar"      -> the CSS class .swiper-scrollbar                 (7/20)
#   "chat-widget"  -> Wix boilerplate engage.wixapps.net/chat-widget-server,
#                     present whether or not chat is enabled          (2/20)

# Field-service software also appears as an embedded scheduler, catching
# businesses whose Serper bookingLinks pointed only at their own site.
SOFTWARE_FINGERPRINTS: list[tuple[str, str]] = [
    ("scheduler.servicetitan.com", "servicetitan"),     # 3/20
    ("housecallpro.com", "housecallpro"),               # 4/20
    ("getjobber.com", "jobber"),                        # 0/20 here, kept for other metros
]

# ONLY the AW- form indicates Google Ads. googleadservices.com and
# googleads.g.doubleclick both scored 0/20 and were removed.
# G- is GA4 analytics and must NEVER count (5/20 sites have it).
_ADS = re.compile(r"gtag/js\?id=AW-|[\"'&?]AW-\d{9,}", re.IGNORECASE)
_PIXEL = re.compile(r"connect\.facebook\.net|fbq\(", re.IGNORECASE)   # 4/20
_FORM = re.compile(r"<form[^>]*>.*?<input[^>]+type=[\"'](?:email|tel)[\"']",
                   re.IGNORECASE | re.DOTALL)
_24_7 = re.compile(r"24[\s/\-]?7|24 hours a day|around the clock", re.IGNORECASE)


# Every key this extractor can produce. `extract_signals` uses it to blank
# the columns for signals that were NOT evaluated on this pass, so a
# rebuild can never leave a stale True behind.
HTML_SIGNAL_KEYS: tuple[str, ...] = (
    "has_chat_widget", "chat_vendor", "software_from_html",
    "has_contact_form", "runs_google_ads", "has_meta_pixel", "claims_24_7",
)


def extract_html_signals(raw_html: str | None,
                         markdown: str | None) -> dict[str, Any]:
    """Return ONLY the signals this input actually provides evidence for.

    A key that was evaluated against real HTML and found absent is `False`
    — a finding. A key with no HTML to evaluate is OMITTED — unknown.
    Coercing the latter to `False` (which is what `(raw_html or "")` used
    to do) breaks `on_missing: skip` at the extractor boundary: a dead-site
    business matched the `no_chat_widget` pain rule for +20 points on zero
    evidence, carried `runs_google_ads` in the fit denominator, and scored
    the same coverage as a fully scraped business. That falsifies ADR-014
    ("a dead website means zero applicable pain rules") and ADR-020
    ("coverage is what distinguishes the tiers").
    """
    signals: dict[str, Any] = {}

    if raw_html is not None:
        html = raw_html.lower()
        chat_vendor = next(
            (v for needle, v in CHAT_FINGERPRINTS if needle in html), None)
        software = next(
            (v for needle, v in SOFTWARE_FINGERPRINTS if needle in html), None)
        signals.update({
            "has_chat_widget": chat_vendor is not None,
            "chat_vendor": chat_vendor,
            "software_from_html": software,
            "has_contact_form": bool(_FORM.search(raw_html)),
            "runs_google_ads": bool(_ADS.search(raw_html)),
            "has_meta_pixel": bool(_PIXEL.search(raw_html)),
        })

    # claims_24_7 reads the markdown rendering, not the HTML, so it is
    # known/unknown independently of the other six.
    if markdown is not None:
        signals["claims_24_7"] = bool(_24_7.search(markdown))

    return signals
