"""Property test for AQI computation. No network."""
from hypothesis import given, settings, strategies as st

from airwise.services.aqi import (
    PM10_BREAKPOINTS,
    PM25_BREAKPOINTS,
    compute_aqi,
    sub_index,
)

conc = st.floats(min_value=0, max_value=5000, allow_nan=False, allow_infinity=False)


@st.composite
def pm_pairs(draw):
    pm25 = draw(st.one_of(st.none(), conc))
    pm10 = draw(st.one_of(st.none(), conc))
    if pm25 is None and pm10 is None:
        pm25 = draw(conc)
    return pm25, pm10


# Feature: airwise, Property 1: AQI is the bounded maximum of sub-indices
# **Validates: Requirements 1.3**
@settings(max_examples=200)
@given(pm_pairs())
def test_aqi_is_bounded_maximum_of_sub_indices(pair):
    pm25, pm10 = pair
    subs = []
    if pm25 is not None:
        subs.append(sub_index(pm25, PM25_BREAKPOINTS))
    if pm10 is not None:
        subs.append(sub_index(pm10, PM10_BREAKPOINTS))

    result = compute_aqi(pm25, pm10)

    assert isinstance(result, int)
    assert 0 <= result <= 500
    assert result == min(500, round(max(subs)))

    if pm25 is not None:
        assert result >= compute_aqi(pm25, None)
    if pm10 is not None:
        assert result >= compute_aqi(None, pm10)
