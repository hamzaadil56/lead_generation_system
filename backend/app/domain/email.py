"""Email parsing and domain comparison.

Pure: no I/O, no ORM, no network. `app/domain/` may not import sqlalchemy,
httpx, fastapi or app.models (ADR-024), and nothing here needs to.

This is the ONE definition of a valid email in the codebase. The harvester
and the API schema both call `normalize_email`, so an address the harvester
saves is always an address a human can edit. `pydantic.EmailStr` is
deliberately not used: `email-validator` is not a project dependency, and
the harvester needs a regex of its own regardless -- two definitions would
drift.
"""
import re

# Deliberately permissive on the local part and strict on the domain: the
# input is scraped HTML, where the realistic failure is a false positive
# (an asset filename, a template placeholder), not a rejected exotic address.
_EMAIL = re.compile(
    r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
    r"@[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?"
    r"(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+$"
)

# Suffixes where the registrable domain is three labels rather than two.
# Short and hard-coded on purpose: the target market is US service
# businesses, and a public-suffix-list dependency would buy nothing here.
_COMPOUND_SUFFIXES = frozenset({
    "co.uk", "com.au", "co.nz", "co.za", "com.br", "co.in",
})

MAX_EMAIL_LENGTH = 254


def normalize_email(raw: str | None) -> str | None:
    """Lowercased and stripped, or None when it is not a usable address."""
    if not raw:
        return None
    value = raw.strip().strip("<>").strip()
    if not value or len(value) > MAX_EMAIL_LENGTH:
        return None
    value = value.lower()
    if value.count("@") != 1 or any(c.isspace() for c in value):
        return None
    if ".." in value:
        return None
    if not _EMAIL.match(value):
        return None
    return value


def email_domain(email: str) -> str:
    """The part after the @, lowercased."""
    return email.partition("@")[2].lower()


def registrable_domain(host: str | None) -> str | None:
    """`https://www.acme.co.uk/about` -> `acme.co.uk`.

    Accepts a bare host or a full URL, so `Business.website` can be passed
    straight in. None when there is no usable domain.
    """
    if not host:
        return None
    value = host.strip().lower()
    if "//" in value:
        value = value.split("//", 1)[1]
    for sep in ("/", "?", "#"):
        value = value.split(sep, 1)[0]
    value = value.split(":", 1)[0]
    if value.startswith("www."):
        value = value[4:]
    labels = [label for label in value.split(".") if label]
    if len(labels) < 2:
        return None
    if len(labels) >= 3 and ".".join(labels[-2:]) in _COMPOUND_SUFFIXES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def domain_stem(host: str | None) -> str | None:
    """The registrable domain with its suffix removed.

    `www.tryleisuration.com` -> `tryleisuration`. This is what the
    harvester's similarity tiers compare.
    """
    registrable = registrable_domain(host)
    if registrable is None:
        return None
    labels = registrable.split(".")
    if len(labels) >= 3 and ".".join(labels[-2:]) in _COMPOUND_SUFFIXES:
        return labels[-3]
    return labels[0]
