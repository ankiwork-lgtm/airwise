"""Property tests for Impact_Engine conditional rows and combine bounds."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from airwise.services.impact import combine, compute_impact
from tests.strategies import profiles, readings


# Feature: airwise, Property 10: Conditional impact rows
@settings(max_examples=100)
@given(profile=profiles(), reading=readings())
def test_property_10_conditional_rows(profile, reading):
    """**Validates: Requirements 5.6, 5.7, 5.8, 5.9**"""
    ids = {row.id for row in compute_impact(profile, reading).rows}
    assert ("transit_swap" in ids) == (profile.commute in ("car", "two_wheeler"))
    assert ("clean_cooking" in ids) == (profile.cooking_fuel == "biomass")
    assert ("biomass_heating_switch" in ids) == (profile.heating == "biomass_burning")
    assert ("purifier_or_diy" in ids) == (not profile.has_purifier)


# Percentages in 0.1 steps, matching the one-decimal precision of the score.
_pcts = st.integers(min_value=0, max_value=1000).map(lambda n: n / 10)


# Feature: airwise, Property 11: Exposure_Score combination bounds
@settings(max_examples=200)
@given(values=st.lists(_pcts, max_size=12), data=st.data())
def test_property_11_combine_bounds(values, data):
    """**Validates: Requirements 5.4, 5.12**"""
    score = combine(values)
    assert 0.0 <= score <= 100.0
    assert score <= sum(values) + 1e-9
    if values:
        assert score >= max(values) - 1e-9
    else:
        assert score == 0.0
    shuffled = data.draw(st.permutations(values))
    assert combine(shuffled) == score


def test_combine_empty_is_zero():
    assert combine([]) == 0.0
