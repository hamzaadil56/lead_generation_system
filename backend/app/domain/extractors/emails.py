"""Candidate email addresses from one page of cached HTML.

Pure: HTML text in, scored candidates out. No I/O, no ORM, no network
(ADR-024). The caller supplies the business's website and name; this module
never looks anything up.

Confidence is a SORT KEY, not a gate. Nothing is exported on the strength of
its score -- `Contact.confirmed_at` is the only gate and only a human sets
it. That asymmetry is why the tiers below are generous: scoring a bad row 0.8
costs a glance, while scoring a good row 0.3 buries the owner's real address
at the bottom of a list that looks like junk, where it gets skipped.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import unquote

from app.domain.email import (domain_stem, email_domain, normalize_email,
                              registrable_domain)

# `discovery_note` values. Exported as constants so the tests and the UI
# cannot drift from the extractor's wording.
MATCHES_WEBSITE = "matches the website domain"
SAME_NAME_OTHER_TLD = "same name as the website, different domain ending"
DOMAIN_VARIANT = "variant of the website domain"
MATCHES_BUSINESS_NAME = "matches the business name"
FREE_PROVIDER = "free mail provider — common for owner-run businesses"
UNRELATED = "unrelated domain — may be a third party"

# Role accounts nobody should cold-email. Bounces and spam complaints from
# these are what damage a sending domain's reputation.
_JUNK_LOCALS = frozenset({
    "noreply", "no-reply", "donotreply", "do-not-reply", "postmaster",
    "abuse", "webmaster", "hostmaster", "mailer-daemon", "unsubscribe",
    "privacy", "legal", "dmca", "security",
})

# Addresses belonging to the site's tooling, not to the business. These come
# out of embedded scripts and CMS boilerplate. Matched on the REGISTRABLE
# domain, so `sentry-next.wixpress.com` is caught by `wixpress.com`.
_VENDOR_DOMAINS = frozenset({
    "wixpress.com", "wix.com", "sentry.io", "squarespace.com", "godaddy.com",
    "wordpress.com", "shopify.com", "hubspot.com", "example.com",
    "example.org", "example.net", "domain.com", "email.com", "yourdomain.com",
    "sentry.wixpress.com",
})

# `logo@2x.png` is the most common false positive in real HTML.
_ASSET_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico",
                   ".css", ".js", ".woff", ".woff2", ".mp4", ".pdf")

# Small businesses run on these constantly. Never rejected -- and checked
# BEFORE every similarity rule, so a business called "Mail Masters" cannot
# reach the containment tier against `gmail.com`.
_FREE_PROVIDERS = frozenset({
    "gmail.com", "googlemail.com", "yahoo.com", "ymail.com", "hotmail.com",
    "outlook.com", "live.com", "msn.com", "aol.com", "icloud.com", "me.com",
    "mac.com", "comcast.net", "sbcglobal.net", "verizon.net", "att.net",
    "bellsouth.net", "cox.net", "charter.net", "earthlink.net", "roadrunner.com",
    "protonmail.com", "proton.me", "gmx.com", "zoho.com",
})

# Trade words shared by unrelated businesses. A stem equal to one of these
# never establishes a relationship, whatever its length.
_GENERIC_TOKENS = frozenset({
    "hvac", "air", "heating", "cooling", "conditioning", "plumbing", "plumber",
    "service", "services", "repair", "repairs", "home", "homes", "comfort",
    "mechanical", "electric", "electrical", "heat", "cool", "climate",
    "energy", "solutions", "company", "contractors", "contracting", "pros",
    "experts", "systems",
})

# Words that turn a domain into a marketing variant of the same name.
_LEADING_AFFIXES = ("try", "get", "go", "my", "the", "use", "visit")
_TRAILING_AFFIXES = ("hq", "co", "inc", "llc", "online", "site", "web", "usa")

# Legal and article noise stripped before matching a business name.
_NAME_NOISE = frozenset({"llc", "inc", "co", "corp", "ltd", "the", "and"})

#: The shorter stem must be at least this long before containment counts.
MIN_STEM_LENGTH = 5

_MAILTO = re.compile(r"""mailto:\s*([^"'>?\s,;]+)""", re.IGNORECASE)
_BARE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


@dataclass(frozen=True)
class HarvestedEmail:
    email: str
    confidence: float
    note: str


def extract_emails(raw_html: str, *, site_domain: str | None,
                   business_name: str | None) -> list[HarvestedEmail]:
    """Candidate addresses from one page, best first.

    Deduplicated within the page, keeping the HIGHEST score for an address
    rather than the first one seen -- a footer `mailto:` and the same address
    in body text must not resolve to whichever the regex happened to reach
    first.
    """
    if not raw_html:
        return []

    raw_candidates = _MAILTO.findall(raw_html) + _BARE.findall(raw_html)

    best: dict[str, HarvestedEmail] = {}
    for raw in raw_candidates:
        email = normalize_email(unquote(raw))
        if email is None or _is_rejected(email):
            continue
        confidence, note = _score(email, site_domain, business_name)
        current = best.get(email)
        if current is None or confidence > current.confidence:
            best[email] = HarvestedEmail(email=email, confidence=confidence,
                                         note=note)

    return sorted(best.values(), key=lambda c: (-c.confidence, c.email))


def _is_rejected(email: str) -> bool:
    local, _, domain = email.partition("@")
    if local in _JUNK_LOCALS:
        return True
    if domain.endswith(_ASSET_SUFFIXES):
        return True
    return registrable_domain(domain) in _VENDOR_DOMAINS


def _score(email: str, site_domain: str | None,
           business_name: str | None) -> tuple[float, str]:
    """The tier table from spec section 5.3, top to bottom, first match wins."""
    domain = email_domain(email)
    registrable = registrable_domain(domain)

    # FIRST, before any similarity rule. See _FREE_PROVIDERS.
    if registrable in _FREE_PROVIDERS:
        return 0.6, FREE_PROVIDER

    stem = domain_stem(domain)
    site_registrable = registrable_domain(site_domain)
    site_stem = domain_stem(site_domain)

    if site_registrable and registrable:
        if registrable == site_registrable or domain.endswith(
                "." + site_registrable):
            return 0.9, MATCHES_WEBSITE
        if stem and site_stem:
            if stem == site_stem:
                return 0.85, SAME_NAME_OTHER_TLD
            if _is_variant_of(stem, site_stem):
                return 0.8, DOMAIN_VARIANT

    name_stem = _name_stem(business_name)
    if stem and name_stem and (stem == name_stem
                               or _is_variant_of(stem, name_stem)):
        return 0.75, MATCHES_BUSINESS_NAME

    return 0.3, UNRELATED


def _is_variant_of(a: str, b: str) -> bool:
    """True when two stems are the same name wearing different clothes."""
    stripped_a, stripped_b = _strip_affixes(a), _strip_affixes(b)
    if stripped_a == stripped_b and _passes_guards(stripped_a):
        return True
    return _boundary_contains(a, b)


def _boundary_contains(a: str, b: str) -> bool:
    """True when the shorter stem sits at the start or end of the longer one.

    Prefix or suffix only, never the middle -- and only when the shorter stem
    passes both guards.
    """
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    if not _passes_guards(short):
        return False
    return long.startswith(short) or long.endswith(short)


def _passes_guards(stem: str) -> bool:
    """The two guards that keep fuzzy matching from degenerating.

    NEITHER IS OPTIONAL, and each catches cases the other misses:

    * The length floor. Without it, site `pipe.test` matches
      `john@pipeline.com` -- `pipe` is a prefix of `pipeline`.
    * The generic-token denylist. Without it, site `acmeplumbing.test`
      matches `john@plumbing.com`. `plumbing` is eight characters and clears
      the floor easily, and HVAC domains are saturated with exactly these
      words, so dropping this guard would score a large fraction of harvested
      contacts 0.8 against businesses they have no relationship to.

    The denylist matters more than the floor in this vertical. Deleting
    either one is caught by exactly one test in
    tests/unit/test_email_extractor.py, by construction.
    """
    return len(stem) >= MIN_STEM_LENGTH and stem not in _GENERIC_TOKENS


def _strip_affixes(stem: str) -> str:
    """`tryleisuration` -> `leisuration`, `acmehq` -> `acme`.

    One affix from each end at most. The length test leaves at least three
    characters behind, so `theco` does not collapse to nothing.
    """
    out = stem
    for prefix in _LEADING_AFFIXES:
        if out.startswith(prefix) and len(out) - len(prefix) >= 3:
            out = out[len(prefix):]
            break
    for suffix in _TRAILING_AFFIXES:
        if out.endswith(suffix) and len(out) - len(suffix) >= 3:
            out = out[:-len(suffix)]
            break
    return out.strip("-")


def _name_stem(business_name: str | None) -> str | None:
    """`Leisuration Air Conditioning, LLC` -> `leisuration`.

    Generic trade words and legal suffixes are dropped, so what remains is
    the part of the name that actually identifies the business.
    """
    if not business_name:
        return None
    words = [w for w in re.split(r"[^a-z0-9]+", business_name.lower()) if w]
    kept = [w for w in words
            if w not in _GENERIC_TOKENS and w not in _NAME_NOISE]
    return "".join(kept) or None
