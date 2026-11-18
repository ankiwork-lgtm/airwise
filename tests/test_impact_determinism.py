from hypothesis import given, settings

from airwise.services.impact import compute_impact
from tests.strategies import profiles, readings


# Feature: airwise, Property 9: Impact_Engine is deterministic and rows are well-formed
@settings(max_examples=100)
@given(profiles(), readings())
def test_impact_deterministic_and_well_formed(profile, reading):
    """**Validates: Requirements 5.1, 5.2, 5.3, 5.5, 13.4**"""
    a = compute_impact(profile, reading)
    b = compute_impact(profile, reading)
    assert a.rows == b.rows
    assert [r.id for r in a.rows] == [r.id for r in b.rows]
    assert a.exposure_score == b.exposure_score

    assert 0 <= len(a.rows) <= 15
    ids = [r.id for r in a.rows]
    assert len(ids) == len(set(ids))
    for r in a.rows:
        assert 0 <= r.exposure_reduction_pct <= 100
        assert 0 <= r.co2_kg_per_day <= 100
        assert 1 <= len(r.basis) <= 200
        assert 1 <= len(r.source_note) <= 200
        assert r.approximate is True
    assert 0 <= a.exposure_score <= 100
