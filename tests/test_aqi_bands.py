"""Property and example tests for CPCB band and GRAP stage mapping. No network."""
from hypothesis import given, settings, strategies as st

from airwise.services.aqi import band_for, compute_aqi, grap_for

BANDS = [
    (0, 50, "Good"),
    (51, 100, "Satisfactory"),
    (101, 200, "Moderate"),
    (201, 300, "Poor"),
    (301, 400, "Very Poor"),
    (401, 500, "Severe"),
]

GRAP = [
    (0, 200, "none"),
    (201, 300, "Stage I"),
    (301, 400, "Stage II"),
    (401, 450, "Stage III"),
    (451, 500, "Stage IV"),
]

aqis = st.integers(min_value=0, max_value=500)


# Feature: airwise, Property 2: Every AQI has exactly one CPCB band with correct boundaries
# **Validates: Requirements 1.4, 13.3**
@settings(max_examples=200)
@given(aqis)
def test_every_aqi_has_exactly_one_correct_band(aqi):
    expected = [name for lo, hi, name in BANDS if lo <= aqi <= hi]
    assert len(expected) == 1
    assert band_for(aqi) == expected[0]


# Feature: airwise, Property 3: GRAP stage mapping
# **Validates: Requirements 1.5, 1.6**
@settings(max_examples=200)
@given(aqis)
def test_grap_stage_mapping(aqi):
    expected = [name for lo, hi, name in GRAP if lo <= aqi <= hi]
    assert len(expected) == 1
    assert grap_for(aqi) == expected[0]


def test_boundaries_exhaustive():
    for lo, hi, name in BANDS:
        assert band_for(lo) == name and band_for(hi) == name
    for lo, hi, name in GRAP:
        assert grap_for(lo) == name and grap_for(hi) == name


def test_reference_points():
    assert compute_aqi(60, None) == 100
    assert compute_aqi(None, 430) == 400
    assert compute_aqi(60, 430) == 400


def test_single_pollutant_input():
    assert compute_aqi(30, None) == 50
    assert compute_aqi(None, 50) == 50
    assert compute_aqi(0, None) == 0
    assert compute_aqi(None, 0) == 0


def test_cap_at_500():
    assert compute_aqi(380, None) == 500
    assert compute_aqi(10000, None) == 500
    assert compute_aqi(None, 10000) == 500
    assert compute_aqi(10000, 10000) == 500
