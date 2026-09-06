import pytest

from app.domain.extractors.emails import (DOMAIN_VARIANT, FREE_PROVIDER,
                                          MATCHES_BUSINESS_NAME,
                                          MATCHES_WEBSITE,
                                          SAME_NAME_OTHER_TLD, UNRELATED,
                                          extract_emails)


def _one(html, site="leisuration.test", name="Leisuration Air"):
    found = extract_emails(html, site_domain=site, business_name=name)
    assert len(found) == 1, f"expected exactly one candidate, got {found}"
    return found[0]


def test_a_mailto_link_is_found():
    got = _one('<a href="mailto:owner@leisuration.test">Email us</a>')
    assert got.email == "owner@leisuration.test"


def test_a_percent_encoded_mailto_is_decoded():
    got = _one('<a href="mailto:owner%40leisuration.test">Email</a>')
    assert got.email == "owner@leisuration.test"


def test_a_bare_address_in_body_text_is_found():
    got = _one("<p>Reach us at owner@leisuration.test any time.</p>")
    assert got.email == "owner@leisuration.test"


def test_the_same_address_twice_on_one_page_yields_one_candidate():
    html = ('<a href="mailto:owner@leisuration.test">a</a>'
            '<p>owner@leisuration.test</p>')
    assert _one(html).email == "owner@leisuration.test"


@pytest.mark.parametrize("local", [
    "noreply", "no-reply", "donotreply", "postmaster", "abuse", "webmaster",
    "hostmaster", "mailer-daemon", "unsubscribe", "privacy", "legal",
])
def test_junk_local_parts_are_rejected(local):
    assert extract_emails(f"<p>{local}@leisuration.test</p>",
                          site_domain="leisuration.test",
                          business_name="Leisuration Air") == []


@pytest.mark.parametrize("domain", [
    "wixpress.com", "sentry-next.wixpress.com", "wix.com", "sentry.io",
    "squarespace.com", "godaddy.com", "wordpress.com", "example.com",
    "example.org", "domain.com", "email.com",
])
def test_vendor_domains_are_rejected(domain):
    """These leak out of embedded scripts and CMS boilerplate, not out of the
    business's own contact details."""
    assert extract_emails(f"<p>hello@{domain}</p>",
                          site_domain="leisuration.test",
                          business_name="Leisuration Air") == []


@pytest.mark.parametrize("html", [
    '<img src="logo@2x.png">',
    '<img srcset="hero@3x.jpg 3x">',
    '<link href="icons@2x.svg">',
    '<script src="bundle@1.css"></script>',
])
def test_asset_filenames_containing_an_at_sign_are_rejected(html):
    """`logo@2x.png` is the most common false positive in real HTML."""
    assert extract_emails(html, site_domain="leisuration.test",
                          business_name="Leisuration Air") == []


def test_empty_html_yields_nothing():
    assert extract_emails("", site_domain="leisuration.test",
                          business_name="Leisuration Air") == []


# --- confidence tiers -------------------------------------------------------

def test_exact_domain_match_scores_highest():
    got = _one("<p>john@leisuration.test</p>")
    assert got.confidence == 0.9
    assert got.note == MATCHES_WEBSITE


def test_a_subdomain_of_the_site_scores_highest():
    got = _one("<p>john@mail.leisuration.test</p>")
    assert got.confidence == 0.9
    assert got.note == MATCHES_WEBSITE


def test_same_name_different_tld():
    """`.example` rather than `.test` on purpose: this tier needs the stem to
    match the site's while the TLD differs, so the two halves of the fixture
    have to sit under different reserved TLDs (RFC 6761 gives us both)."""
    got = _one("<p>john@leisuration.example</p>")
    assert got.confidence == 0.85
    assert got.note == SAME_NAME_OTHER_TLD


def test_a_try_prefixed_marketing_domain_is_a_variant_not_a_stranger():
    """The case exact-equality matching gets wrong: `tryleisuration.test`
    against site `leisuration.test` is almost certainly the owner, and
    scoring it 0.3 buries it at the bottom of the list looking like junk."""
    got = _one("<p>john@tryleisuration.test</p>")
    assert got.confidence == 0.8
    assert got.note == DOMAIN_VARIANT


def test_a_suffixed_domain_is_a_variant():
    got = _one("<p>john@leisurationhvac.test</p>")
    assert got.confidence == 0.8
    assert got.note == DOMAIN_VARIANT


def test_a_domain_matching_the_business_name_but_not_the_website():
    """Reachable only when the WEBSITE stem is unrelated to the name -- a
    legacy or rebranded domain. Do not use a site like `leisurationair.test`
    here: its stem starts with `leisuration`, so the containment rule fires
    first and returns 0.8, and the test would be asserting the wrong tier."""
    got = _one("<p>john@leisuration.test</p>", site="coolbreezehvac.test",
               name="Leisuration Air Conditioning, LLC")
    assert got.confidence == 0.75
    assert got.note == MATCHES_BUSINESS_NAME


@pytest.mark.parametrize("domain", [
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com",
    "icloud.com", "comcast.net", "sbcglobal.net",
])
def test_free_providers_score_middling_and_are_never_rejected(domain):
    """Most owner-run HVAC businesses mail from a free provider. A rule that
    kept only addresses matching the business domain would throw away the
    single most common real case."""
    got = _one(f"<p>john@{domain}</p>")
    assert got.confidence == 0.6
    assert got.note == FREE_PROVIDER


def test_a_free_provider_never_reaches_a_similarity_tier():
    """Checked before every similarity rule. Otherwise a business called
    'Mail Masters' reaches the containment tier against gmail.com."""
    got = _one("<p>john@gmail.com</p>", site="mailmasters.test",
               name="Mail Masters")
    assert got.confidence == 0.6


def test_an_unrelated_domain_scores_lowest():
    got = _one("<p>hello@somewebdesignco.test</p>")
    assert got.confidence == 0.3
    assert got.note == UNRELATED


# --- the guards -------------------------------------------------------------
#
# Each of the next two isolates ONE guard: the case is constructed so that
# exactly one guard rejects it, and the test therefore fails if that guard is
# deleted. A case like `john@repair.test` vs site `air.test` LOOKS like a
# length-floor test but trips both guards at once (`air` is under five
# characters AND on the denylist), so it survives either guard's removal and
# tests neither. A guard test that passes with its own guard gone is not a
# test of that guard.

def test_the_length_floor_stops_a_short_stem_matching_a_longer_word():
    """`pipe` is a prefix of `pipeline` and is not a generic token, so only
    the five-character floor rejects this."""
    got = _one("<p>john@pipeline.test</p>", site="pipe.test", name="Pipe Co")
    assert got.confidence == 0.3
    assert got.note == UNRELATED


def test_the_generic_token_denylist_stops_a_shared_trade_word():
    """`plumbing` is a suffix of `acmeplumbing` and its eight characters clear
    the floor, so only the denylist rejects this. HVAC domains are saturated
    with these words -- without the denylist a large fraction of harvested
    contacts would score 0.8 against businesses they have no relationship
    to."""
    got = _one("<p>john@plumbing.test</p>", site="acmeplumbing.test",
               name="Acme Plumbing")
    assert got.confidence == 0.3
    assert got.note == UNRELATED


# --- ordering ---------------------------------------------------------------

def test_candidates_come_back_best_first():
    html = ("<p>hello@somewebdesignco.test</p>"
            "<p>john@gmail.com</p>"
            "<p>owner@leisuration.test</p>")
    found = extract_emails(html, site_domain="leisuration.test",
                           business_name="Leisuration Air")
    assert [c.confidence for c in found] == [0.9, 0.6, 0.3]


def test_the_highest_confidence_wins_when_one_address_scores_twice():
    """Dedup keeps the best score, never the first seen."""
    html = ('<a href="mailto:owner@leisuration.test">a</a>'
            '<p>owner@leisuration.test</p>')
    assert _one(html).confidence == 0.9


def test_a_business_with_no_website_still_scores_against_its_name():
    got = _one("<p>john@leisuration.test</p>", site=None,
               name="Leisuration Air")
    assert got.confidence == 0.75
