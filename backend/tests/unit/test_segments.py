import pytest
from app.domain.segments import Segment, segment_for


@pytest.mark.parametrize("count,expected", [
    (43, None),                      # below the floor — not a segment at all
    (72, Segment.EMERGING),
    (199, Segment.EMERGING),
    (200, Segment.GROWTH),
    (1999, Segment.GROWTH),
    (2000, Segment.ESTABLISHED),
    (4999, Segment.ESTABLISHED),
    (5000, Segment.ENTERPRISE),
    (10712, Segment.ENTERPRISE),     # real: One Hour Air Conditioning
    (None, None),
])
def test_segment_boundaries(count, expected):
    assert segment_for(count) == expected
