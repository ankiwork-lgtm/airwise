import json

from hypothesis import given, settings

from airwise.models import Plan
from airwise.services.fallback import build_fallback_plan
from airwise.services.impact import compute_impact
from tests.strategies import plans, profiles, readings


# Feature: airwise, Property 14: Fallback_Plan is schema-valid and independent of the LLM
@settings(max_examples=100)
@given(profiles(), readings())
def test_fallback_plan_schema_valid_and_llm_independent(profile, reading):
    """**Validates: Requirements 7.6, 6.4**"""
    impact = compute_impact(profile, reading)
    # No LLM client is configured or patched: the builder is a pure function.
    plan = build_fallback_plan(profile, reading, impact)
    assert Plan.model_validate(plan.model_dump()) == plan
    assert plan.fallback is True
    assert plan.estimated == (reading.source == "estimated")
    assert plan.impact_table == list(impact.rows)
    assert plan.exposure_score == impact.exposure_score
    assert build_fallback_plan(profile, reading, impact) == plan


# Feature: airwise, Property 16: Plan JSON round trip
@settings(max_examples=100)
@given(plans())
def test_plan_json_round_trip(plan):
    """**Validates: Requirements 13.5**"""
    restored = Plan.model_validate_json(plan.model_dump_json())
    assert restored == plan
    assert Plan.model_validate(json.loads(json.dumps(plan.model_dump()))) == plan
