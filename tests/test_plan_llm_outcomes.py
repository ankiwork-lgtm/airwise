import asyncio
import logging
import os

from hypothesis import given, settings
from hypothesis import strategies as st

from airwise.config import Deadline
from airwise.models import AirReading, HouseholdProfile, Plan
from airwise.services.impact import compute_impact
from airwise.services.llm import LLMUnavailable
from airwise.services.plan import generate_plan
from tests.strategies import profiles, readings

_FACTORS = [
    "stubble_burning",
    "firecrackers",
    "biomass_cooking_heating",
    "two_wheelers",
    "metro_use",
]
_OUTCOMES = ["valid", "unparsable", "schema_invalid", "error", "timeout"]
_KEYS = ["set", "empty", "unset"]

_text = st.text(min_size=1, max_size=300)


class FakeLLM:
    """Counts calls and returns or raises the configured outcome."""

    def __init__(self, result=None, exc=None):
        self.calls = 0
        self._result = result
        self._exc = exc

    async def complete_json(self, **kwargs):
        self.calls += 1
        if self._exc is not None:
            raise self._exc
        return self._result


def _llm_item(impact_ids):
    return st.fixed_dictionaries(
        {
            "text": _text,
            "why_it_matters": _text,
            "impact_id": st.none()
            | (st.sampled_from(impact_ids) if impact_ids else st.nothing())
            | st.text(max_size=20),
            "context_factor": st.none() | st.sampled_from(_FACTORS),
        }
    )


def _llm_plan(impact_ids):
    def items(n):
        return st.lists(_llm_item(impact_ids), min_size=1, max_size=n)

    return st.fixed_dictionaries(
        {
            "routine": st.fixed_dictionaries(
                {s: items(3) for s in ("morning", "commute", "midday", "evening")}
            ),
            "indoor_hacks": items(5),
            "swaps": items(5),
            "vulnerable_note": st.text(max_size=500),
        }
    )


_schema_breakers = st.sampled_from(
    ["missing_key", "extra_key", "empty_list", "too_many", "wrong_type"]
)


def _break(plan: dict, how: str) -> dict:
    plan = {**plan, "routine": dict(plan["routine"])}
    if how == "missing_key":
        del plan["swaps"]
    elif how == "extra_key":
        plan["extra"] = 1
    elif how == "empty_list":
        plan["routine"]["morning"] = []
    elif how == "too_many":
        plan["indoor_hacks"] = plan["indoor_hacks"][:1] * 6
    else:
        plan["vulnerable_note"] = 123
    return plan


def _set_key(mode: str):
    old = os.environ.get("ANTHROPIC_API_KEY")
    if mode == "set":
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
    elif mode == "empty":
        os.environ["ANTHROPIC_API_KEY"] = ""
    else:
        os.environ.pop("ANTHROPIC_API_KEY", None)
    return old


def _restore_key(old):
    if old is None:
        os.environ.pop("ANTHROPIC_API_KEY", None)
    else:
        os.environ["ANTHROPIC_API_KEY"] = old


# Feature: airwise, Property 13: LLM outcomes map to a valid Plan with at most one call
@settings(max_examples=100, deadline=None)
@given(
    data=st.data(),
    profile=profiles(),
    reading=readings(),
    outcome=st.sampled_from(_OUTCOMES),
    key=st.sampled_from(_KEYS),
)
def test_llm_outcomes_map_to_valid_plan_with_at_most_one_call(data, profile, reading, outcome, key):
    """**Validates: Requirements 6.1, 6.5, 6.6, 6.11, 7.1, 7.2, 7.3, 7.4, 7.5, 7.8, 12.7**"""
    impact = compute_impact(profile, reading)
    ids = [r.id for r in impact.rows]
    valid = data.draw(_llm_plan(ids))

    if outcome == "valid":
        llm = FakeLLM(result=valid)
    elif outcome == "unparsable":
        llm = FakeLLM(exc=LLMUnavailable("LLM call failed (JSONDecodeError)."))
    elif outcome == "schema_invalid":
        llm = FakeLLM(result=_break(valid, data.draw(_schema_breakers)))
    elif outcome == "error":
        llm = FakeLLM(exc=RuntimeError("boom"))
    else:
        llm = FakeLLM(exc=TimeoutError())

    old = _set_key(key)
    try:
        plan = asyncio.run(generate_plan(profile, reading, llm=llm, deadline=Deadline()))
    finally:
        _restore_key(old)

    # Always a valid Plan, at most one LLM call.
    assert Plan.model_validate(plan.model_dump()) == plan
    assert llm.calls <= 1
    assert plan.estimated == (reading.source == "estimated")
    assert plan.impact_table == list(impact.rows)
    assert plan.exposure_score == impact.exposure_score

    if key != "set":
        assert llm.calls == 0
        assert plan.fallback is True
    else:
        assert llm.calls == 1
        assert plan.fallback is (outcome != "valid")

    # Figures are server-owned: copied from the table or absent.
    by_id = {r.id: r for r in impact.rows}
    all_items = list(
        plan.routine.morning + plan.routine.commute + plan.routine.midday + plan.routine.evening
    )
    all_items += plan.indoor_hacks + plan.swaps
    for item in all_items:
        if item.impact is None:
            continue
        row = by_id[item.impact_id]
        assert item.impact.exposure_reduction_pct == row.exposure_reduction_pct
        assert item.impact.co2_kg_per_day == row.co2_kg_per_day


def test_llm_failure_logs_error_class_without_message(monkeypatch, caplog):
    profile = HouseholdProfile(
        city="Delhi",
        kids=False,
        elderly=False,
        respiratory=False,
        commute="car",
        cooking_fuel="lpg",
        heating="none",
        has_purifier=False,
        ventilation="sometimes",
    )
    reading = AirReading(
        location_name="Delhi",
        latitude=28.6,
        longitude=77.2,
        pm2_5=120.0,
        pm10=200.0,
        aqi=300,
        band="Poor",
        grap_stage="Stage I",
        source="estimated",
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    caplog.set_level(logging.WARNING, logger="airwise")

    llm = FakeLLM(exc=RuntimeError("SECRET-PROMPT-ECHO"))
    plan = asyncio.run(generate_plan(profile, reading, llm=llm, deadline=Deadline()))

    assert plan.fallback is True
    assert "fell back to deterministic rules: RuntimeError" in caplog.text
    assert "SECRET-PROMPT-ECHO" not in caplog.text
    assert "test-key" not in caplog.text
