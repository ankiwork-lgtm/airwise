"""Property 12: Plan impact figures always equal table figures."""
import asyncio

from hypothesis import HealthCheck, given, settings, strategies as st

from airwise.config import Deadline
from airwise.models import ImpactFigures
from airwise.services.impact import compute_impact
from airwise.services.plan import _SLOTS, generate_plan

from tests.strategies import llm_plans, profiles, readings


class _FakeLLM:
    def __init__(self, payload):
        self.payload = payload

    async def complete_json(self, **kwargs):
        return self.payload


def _all_items(plan):
    for slot in _SLOTS:
        yield from getattr(plan.routine, slot)
    yield from plan.indoor_hacks
    yield from plan.swaps


# Feature: airwise, Property 12: Plan impact figures always equal table figures
# **Validates: Requirements 6.7**
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(profile=profiles(), reading=readings(), data=st.data())
def test_plan_figures_equal_table(monkeypatch, profile, reading, data):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    impact = compute_impact(profile, reading)
    table = {r.id: r for r in impact.rows}
    payload = data.draw(llm_plans(valid_ids=list(table)))

    plan = asyncio.run(
        generate_plan(profile, reading, llm=_FakeLLM(payload), deadline=Deadline())
    )

    assert plan.impact_table == list(impact.rows)
    assert plan.exposure_score == impact.exposure_score
    for item in _all_items(plan):
        row = table.get(item.impact_id) if item.impact_id is not None else None
        if row is None:
            assert item.impact is None
        else:
            assert item.impact == ImpactFigures(
                exposure_reduction_pct=row.exposure_reduction_pct,
                co2_kg_per_day=row.co2_kg_per_day,
                approximate=True,
            )


# Same property, restricted to payloads that pass schema validation (sanitize path).
# **Validates: Requirements 6.7**
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(profile=profiles(), reading=readings(), data=st.data())
def test_plan_figures_equal_table_valid_llm_output(monkeypatch, profile, reading, data):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    impact = compute_impact(profile, reading)
    table = {r.id: r for r in impact.rows}
    payload = data.draw(llm_plans(valid_ids=list(table), allow_extra_keys=False))

    plan = asyncio.run(
        generate_plan(profile, reading, llm=_FakeLLM(payload), deadline=Deadline())
    )

    assert plan.fallback is False
    assert plan.impact_table == list(impact.rows)
    for item in _all_items(plan):
        row = table.get(item.impact_id) if item.impact_id is not None else None
        if row is None:
            assert item.impact is None
        else:
            assert item.impact.exposure_reduction_pct == row.exposure_reduction_pct
            assert item.impact.co2_kg_per_day == row.co2_kg_per_day
