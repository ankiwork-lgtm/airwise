import asyncio
import os
from unittest.mock import patch

from hypothesis import given, settings
from hypothesis import strategies as st

from airwise.config import Deadline
from airwise.models import AirReading, HouseholdProfile, Plan
from airwise.services.fallback import build_fallback_plan
from airwise.services.impact import compute_impact
from airwise.services.plan import generate_plan
from tests.strategies import profiles, readings

_FACTORS = [
    "stubble_burning",
    "firecrackers",
    "biomass_cooking_heating",
    "two_wheelers",
    "metro_use",
]
_item = st.fixed_dictionaries(
    {
        "text": st.text(min_size=1, max_size=300),
        "why_it_matters": st.text(min_size=1, max_size=300),
        "impact_id": st.none() | st.text(max_size=20),
        "context_factor": st.none() | st.sampled_from(_FACTORS),
    }
)


def _items(n):
    return st.lists(_item, min_size=1, max_size=n)


# Adversarial but schema-valid LLM output: arbitrary note, arbitrary/missing tags.
_llm_raw = st.fixed_dictionaries(
    {
        "routine": st.fixed_dictionaries(
            {k: _items(3) for k in ("morning", "commute", "midday", "evening")}
        ),
        "indoor_hacks": _items(5),
        "swaps": _items(5),
        "vulnerable_note": st.text(max_size=500),
    }
)


class _FakeLLM:
    def __init__(self, raw):
        self.raw = raw

    async def complete_json(self, **kwargs):
        return self.raw


def _relevant_factors(profile: HouseholdProfile, reading: AirReading) -> set[str]:
    out = set()
    if profile.cooking_fuel == "biomass" or profile.heating == "biomass_burning":
        out.add("biomass_cooking_heating")
    if profile.commute == "two_wheeler":
        out.add("two_wheelers")
    if profile.commute == "bus_metro":
        out.add("metro_use")
    if reading.aqi >= 201:
        out |= {"stubble_burning", "firecrackers"}
    return out


def _check(plan: Plan, profile: HouseholdProfile, reading: AirReading) -> None:
    assert plan.estimated == (reading.source == "estimated")
    note = plan.vulnerable_note.lower()
    assert len(plan.vulnerable_note) <= 500
    for present, word in (
        (profile.kids, "kids"),
        (profile.elderly, "elderly"),
        (profile.respiratory, "respiratory"),
    ):
        if present:
            assert 1 <= len(plan.vulnerable_note)
            assert word in note
    relevant = _relevant_factors(profile, reading)
    if relevant:
        tags = {
            i.context_factor
            for slot in ("morning", "commute", "midday", "evening")
            for i in getattr(plan.routine, slot)
        }
        assert tags & relevant


# Feature: airwise, Property 15: Plan content guarantees
@settings(max_examples=100)
@given(profiles(), readings())
def test_fallback_plan_content_guarantees(profile, reading):
    """**Validates: Requirements 3.4, 6.8, 6.9**"""
    plan = build_fallback_plan(profile, reading, compute_impact(profile, reading))
    assert plan.fallback is True
    _check(plan, profile, reading)


# Feature: airwise, Property 15: Plan content guarantees
@settings(max_examples=100)
@given(profiles(), readings(), _llm_raw)
def test_llm_plan_content_guarantees(profile, reading, raw):
    """**Validates: Requirements 3.4, 6.8, 6.9**"""
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
        plan = asyncio.run(generate_plan(profile, reading, llm=_FakeLLM(raw), deadline=Deadline()))
    assert plan.fallback is False
    _check(plan, profile, reading)
