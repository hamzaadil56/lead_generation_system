from app.domain.booking import BookingVendor, classify_booking_links


def test_servicetitan_detected_from_real_url():
    info = classify_booking_links([
        "https://book.servicetitan.com/r403q9wgygvty8ghzvbhag5i?rwg_token=AE37R_ga"
    ])
    assert info.vendor is BookingVendor.SERVICETITAN
    assert info.has_booking is True
    assert info.is_phone_only is False


def test_housecallpro_detected_from_real_url():
    info = classify_booking_links([
        "https://allstarairtexas.com/contact/",
        "https://book.housecallpro.com/book/All-Star-AC/25086315e0864b46?v2=true",
    ])
    assert info.vendor is BookingVendor.HOUSECALLPRO   # vendor beats own-site


def test_own_site_booking_only():
    info = classify_booking_links(["https://www.houseproac.com/request-service/"])
    assert info.vendor is BookingVendor.OWN
    assert info.has_booking is True
    assert info.is_phone_only is False


def test_absent_key_means_phone_only():
    # 6 of 20 Houston records omitted bookingLinks entirely (ADR-021).
    # Absence IS the signal, worth 25 pain points.
    info = classify_booking_links(None)
    assert info.vendor is BookingVendor.NONE
    assert info.has_booking is False
    assert info.is_phone_only is True


def test_empty_list_is_treated_the_same_as_absent():
    assert classify_booking_links([]).is_phone_only is True
