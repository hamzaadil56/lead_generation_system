import enum
from dataclasses import dataclass


class BookingVendor(enum.StrEnum):
    SERVICETITAN = "servicetitan"
    JOBBER = "jobber"
    HOUSECALLPRO = "housecallpro"
    OWN = "own"
    NONE = "none"


# Ordered: a recognised vendor always beats a generic own-site link.
_FINGERPRINTS: list[tuple[str, BookingVendor]] = [
    ("book.servicetitan.com", BookingVendor.SERVICETITAN),
    ("servicetitan.com", BookingVendor.SERVICETITAN),
    ("book.housecallpro.com", BookingVendor.HOUSECALLPRO),
    ("housecallpro.com", BookingVendor.HOUSECALLPRO),
    ("clienthub.getjobber.com", BookingVendor.JOBBER),
    ("getjobber.com", BookingVendor.JOBBER),
]


@dataclass(frozen=True)
class BookingInfo:
    vendor: BookingVendor
    has_booking: bool
    is_phone_only: bool


def classify_booking_links(links: list[str] | None) -> BookingInfo:
    if not links:
        return BookingInfo(BookingVendor.NONE, has_booking=False, is_phone_only=True)
    joined = " ".join(links).lower()
    for needle, vendor in _FINGERPRINTS:
        if needle in joined:
            return BookingInfo(vendor, has_booking=True, is_phone_only=False)
    return BookingInfo(BookingVendor.OWN, has_booking=True, is_phone_only=False)
