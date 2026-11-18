"""Shared Hypothesis strategies."""
from __future__ import annotations

from hypothesis import strategies as st

from airwise.models import AirReading, HouseholdProfile
from airwise.services.aqi import band_for, compute_aqi, grap_for

_trimmed_text = (
    st.text(min_size=1, max_size=100)
    .filter(lambda s: s == s.strip() and len(s) > 0)
)


@st.composite
def profiles(draw) -> HouseholdProfile:
    return HouseholdProfile(
        city=draw(_trimmed_text),
        kids=draw(st.booleans()),
        elderly=draw(st.booleans()),
        respiratory=draw(st.booleans()),
        commute=draw(st.sampled_from(["car", "two_wheeler", "bus_metro", "walk_cycle", "work_from_home"])),
        cooking_fuel=draw(st.sampled_from(["lpg", "png", "induction", "biomass"])),
        heating=draw(st.sampled_from(["none", "electric", "biomass_burning"])),
        has_purifier=draw(st.booleans()),
        ventilation=draw(st.sampled_from(["open_often", "sometimes", "mostly_closed"])),
    )


_pm = st.floats(min_value=0, max_value=5000, allow_nan=False, allow_infinity=False)


@st.composite
def readings(draw) -> AirReading:
    pm25 = draw(st.none() | _pm)
    pm10 = draw(st.none() | _pm) if pm25 is not None else draw(_pm)
    aqi = compute_aqi(pm25, pm10)
    return AirReading(
        location_name=draw(_trimmed_text),
        latitude=draw(st.floats(min_value=-90, max_value=90, allow_nan=False)),
        longitude=draw(st.floats(min_value=-180, max_value=180, allow_nan=False)),
        pm2_5=pm25,
        pm10=pm10,
        aqi=aqi,
        band=band_for(aqi),
        grap_stage=grap_for(aqi),
        source=draw(st.sampled_from(["live", "estimated"])),
    )


# --- Plan strategy -----------------------------------------------------------
from airwise.models import ImpactFigures, ImpactRow, Plan, PlanItem, Routine  # noqa: E402

_short_text = st.text(min_size=1, max_size=300)
_pct = st.floats(min_value=0, max_value=100, allow_nan=False, allow_infinity=False)
_co2 = st.floats(min_value=0, max_value=100, allow_nan=False, allow_infinity=False)


@st.composite
def _impact_figures(draw) -> ImpactFigures:
    return ImpactFigures(
        exposure_reduction_pct=draw(_pct), co2_kg_per_day=draw(_co2), approximate=True
    )


@st.composite
def _plan_items(draw) -> PlanItem:
    return PlanItem(
        text=draw(_short_text),
        why_it_matters=draw(_short_text),
        impact_id=draw(st.none() | st.text(min_size=1, max_size=50)),
        context_factor=draw(
            st.none()
            | st.sampled_from(
                [
                    "stubble_burning",
                    "firecrackers",
                    "biomass_cooking_heating",
                    "two_wheelers",
                    "metro_use",
                ]
            )
        ),
        impact=draw(st.none() | _impact_figures()),
    )


@st.composite
def _impact_rows(draw) -> ImpactRow:
    return ImpactRow(
        id=draw(st.text(min_size=1, max_size=50)),
        action=draw(st.text(min_size=1, max_size=200)),
        basis=draw(st.text(min_size=1, max_size=200)),
        source_note=draw(st.text(min_size=1, max_size=200)),
        exposure_reduction_pct=draw(_pct),
        co2_kg_per_day=draw(_co2),
        approximate=True,
    )


@st.composite
def plans(draw) -> Plan:
    def items(max_size: int):
        return st.lists(_plan_items(), min_size=1, max_size=max_size)

    return Plan(
        routine=Routine(
            morning=draw(items(3)),
            commute=draw(items(3)),
            midday=draw(items(3)),
            evening=draw(items(3)),
        ),
        indoor_hacks=draw(items(5)),
        swaps=draw(items(5)),
        vulnerable_note=draw(st.text(max_size=500)),
        impact_table=draw(st.lists(_impact_rows(), max_size=15)),
        exposure_score=draw(_pct),
        fallback=draw(st.booleans()),
        estimated=draw(st.booleans()),
    )


# --- Raw LLM output strategy -------------------------------------------------
_CONTEXT_FACTORS = [
    "stubble_burning",
    "firecrackers",
    "biomass_cooking_heating",
    "two_wheelers",
    "metro_use",
]
_extra_number = st.one_of(
    st.integers(min_value=-1000, max_value=1000),
    st.floats(allow_nan=False, allow_infinity=False, min_value=-1e6, max_value=1e6),
)


def llm_plans(valid_ids=(), allow_extra_keys: bool = True):
    """Raw dicts shaped like LLM output, as parsed from JSON.

    impact_id mixes ids from ``valid_ids`` with bogus ids and None. Items may carry
    an ``impact`` dict with made-up figures and extra numeric keys; with extra keys
    the dict fails LLMPlan validation, so callers see both the sanitize and fallback paths.
    """
    impact_id = st.none() | st.text(min_size=1, max_size=40)
    if valid_ids:
        impact_id = impact_id | st.sampled_from(list(valid_ids))

    @st.composite
    def item(draw) -> dict:
        d = {
            "text": draw(st.text(min_size=1, max_size=300)),
            "why_it_matters": draw(st.text(min_size=1, max_size=300)),
            "impact_id": draw(impact_id),
            "context_factor": draw(st.none() | st.sampled_from(_CONTEXT_FACTORS)),
        }
        if allow_extra_keys and draw(st.booleans()):
            d["impact"] = {
                "exposure_reduction_pct": draw(_extra_number),
                "co2_kg_per_day": draw(_extra_number),
                "approximate": draw(st.booleans()),
            }
            d["exposure_reduction_pct"] = draw(_extra_number)
            d["co2_kg_per_day"] = draw(_extra_number)
        return d

    def items(max_size: int):
        return st.lists(item(), min_size=1, max_size=max_size)

    return st.fixed_dictionaries(
        {
            "routine": st.fixed_dictionaries(
                {
                    "morning": items(3),
                    "commute": items(3),
                    "midday": items(3),
                    "evening": items(3),
                }
            ),
            "indoor_hacks": items(5),
            "swaps": items(5),
            "vulnerable_note": st.text(max_size=500),
        }
    )
