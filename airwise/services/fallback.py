"""Fallback_Plan builder: a deterministic, schema-valid Plan from the Impact_Table.

Pure function: no LLM, no I/O, no clock.
"""

from __future__ import annotations

from airwise.models import (
    AirReading,
    ContextFactor,
    HouseholdProfile,
    ImpactRow,
    Plan,
    PlanItem,
    Routine,
)
from airwise.services.impact import POOR_AQI_MIN, ImpactResult

_TEXT_MAX = 300
_NOTE_MAX = 500

_INDOOR_IDS = ("purifier_or_diy", "close_windows_peak", "wet_cleaning")
_SWAP_IDS = (
    "clean_cooking",
    "biomass_heating_switch",
    "transit_swap",
    "carpool",
    "no_burning_pledge",
)

_BAND_MORNING = {
    "Good": "Air is good: open windows briefly for fresh air and enjoy outdoor exercise.",
    "Satisfactory": "Air is acceptable: exercise outdoors as usual, but prefer a less busy route.",
    "Moderate": "Keep outdoor exercise light and short; avoid busy roads.",
    "Poor": "Move workouts indoors or to a low-traffic park, and keep them short.",
    "Very Poor": "Skip outdoor exercise today and do a light indoor workout instead.",
    "Severe": "Stay indoors for exercise and avoid any outdoor activity before mid-morning.",
}
_BAND_MIDDAY = {
    "Good": "Take your breaks outside if you like; air quality is fine.",
    "Satisfactory": "Short outdoor breaks are fine for most people.",
    "Moderate": "Keep outdoor breaks short and away from traffic.",
    "Poor": "Take breaks indoors and limit time outside.",
    "Very Poor": "Stay indoors at midday and keep windows closed.",
    "Severe": "Stay indoors all day; avoid errands unless essential.",
}
_BAND_EVENING = {
    "Good": "Evening walks are fine tonight.",
    "Satisfactory": "Evening walks are fine; avoid heavy traffic areas.",
    "Moderate": "Keep evening walks short and choose quiet streets.",
    "Poor": "Avoid evening outdoor activity when pollution tends to build up.",
    "Very Poor": "Stay in this evening and keep the main room sealed and filtered if you can.",
    "Severe": "Stay in this evening; avoid going out until the air improves.",
}
_BAND_WHY = {
    "Good": "Low pollution means little added health risk from normal activity.",
    "Satisfactory": "Pollution is low but sensitive people may still notice symptoms.",
    "Moderate": "Moderate pollution can irritate lungs of sensitive people.",
    "Poor": "Poor air can cause breathing discomfort with prolonged exposure.",
    "Very Poor": "Very poor air can cause respiratory illness on prolonged exposure.",
    "Severe": "Severe air can affect even healthy people and seriously harm sensitive ones.",
}

_COMMUTE_TEXT = {
    "car": "Drive with windows up and the AC on recirculate; avoid peak-hour traffic.",
    "two_wheeler": "Wear a well-fitted N95 mask while riding and avoid congested roads.",
    "bus_metro": "Prefer the metro or bus and wear a mask on crowded platforms and at stops.",
    "walk_cycle": "Choose side streets or parks over main roads when walking or cycling.",
    "work_from_home": "Work from home today and skip non-essential trips.",
}
_COMMUTE_WHY = {
    "car": "Closed windows and recirculated air reduce in-cabin exposure to road dust and exhaust.",
    "two_wheeler": "Riders breathe traffic exhaust directly, so a mask helps cut exposure.",
    "bus_metro": (
        "Shared transport lowers emissions per person, and a mask lowers exposure in crowds."
    ),
    "walk_cycle": "Streets away from traffic have lower concentrations of pollutants.",
    "work_from_home": "Staying home avoids the outdoor exposure of a commute.",
}


def _item(
    text: str,
    why: str,
    row: ImpactRow | None = None,
    context_factor: ContextFactor | None = None,
) -> PlanItem:
    """Build a PlanItem, trimming text to the model limits."""
    return PlanItem(
        text=text[:_TEXT_MAX],
        why_it_matters=(why or "Helps reduce your exposure to polluted air.")[:_TEXT_MAX],
        impact_id=row.id if row else None,
        context_factor=context_factor,
        impact=row.figures() if row else None,
    )


def build_vulnerable_note(profile: HouseholdProfile) -> str:
    """Return a health guidance note naming vulnerable groups in the household.

    Args:
        profile: Household profile indicating presence of kids, elderly, or respiratory issues.

    Returns:
        A tailored precautions sentence trimmed to 500 characters.
    """
    groups = []
    if profile.kids:
        groups.append("kids")
    if profile.elderly:
        groups.append("elderly members")
    if profile.respiratory:
        groups.append("members with respiratory conditions")
    if not groups:
        return (
            "No kids, elderly, or respiratory-sensitive members were listed; "
            "normal precautions apply."
        )
    names = ", ".join(groups)
    note = (
        f"Take extra care for {names}: keep them indoors on high-pollution days, "
        "use a purifier in their room, and consult a doctor if symptoms such as "
        "coughing, wheezing, or breathlessness appear."
    )
    return note[:_NOTE_MAX]


def context_factors(profile: HouseholdProfile, reading: AirReading) -> list[ContextFactor]:
    """Identify local and behavioral pollution factors relevant to household.

    Args:
        profile: Household profile detailing commute mode, heating, and cooking fuel.
        reading: AirReading providing current location AQI.

    Returns:
        List of matching ContextFactor identifiers.
    """
    factors: list[ContextFactor] = []
    if profile.cooking_fuel == "biomass" or profile.heating == "biomass_burning":
        factors.append("biomass_cooking_heating")
    if profile.commute == "two_wheeler":
        factors.append("two_wheelers")
    if profile.commute == "bus_metro":
        factors.append("metro_use")
    if reading.aqi >= POOR_AQI_MIN:
        factors.append("stubble_burning")
        factors.append("firecrackers")
    return factors


FACTOR_ITEM: dict[ContextFactor, tuple[str, str]] = {
    "biomass_cooking_heating": (
        "Avoid biomass for cooking and heating today; ventilate the kitchen while cooking.",
        "Burning biomass indoors releases fine particles that raise household exposure.",
    ),
    "two_wheelers": (
        "Wear an N95 mask while riding a two-wheeler and avoid peak traffic.",
        "Two-wheeler riders are exposed to exhaust at close range.",
    ),
    "metro_use": (
        "Use the metro for longer trips and wear a mask on crowded platforms.",
        "Metro travel cuts per-person emissions and avoids street-level exhaust.",
    ),
    "stubble_burning": (
        "Check smoke forecasts: crop-residue (stubble) burning season can worsen air; "
        "stay indoors on smoky days.",
        "Stubble smoke drifting into cities adds fine particles on top of local pollution.",
    ),
    "firecrackers": (
        "Avoid firecrackers and stay away from areas where they are burnt, "
        "especially around festivals.",
        "Firecracker smoke sharply raises short-term fine particle levels.",
    ),
}


_INDOOR_DEFAULT = (
    "Keep indoor air clean: avoid smoke, incense, and dry sweeping.",
    "Indoor sources add to pollution you breathe even when outdoor air is fine.",
)
_SWAP_DEFAULT = (
    "Walk, cycle, or use public transport for short trips when you can.",
    "Fewer fuel-burning trips cut both local pollution and CO2 emissions.",
)
_MAX_LIST_ITEMS = 5


def _rows_to_items(
    rows: dict[str, ImpactRow], ids: tuple[str, ...], default: tuple[str, str]
) -> list[PlanItem]:
    """Items for the impact rows named in ``ids``, or one default item when none apply."""
    items = [_item(row.action, row.basis, row) for rid in ids if (row := rows.get(rid))]
    return items or [_item(*default)]


def _commute_item(
    profile: HouseholdProfile, rows: dict[str, ImpactRow], factors: list[ContextFactor]
) -> PlanItem:
    """The commute item, tied to the N95 row unless the household works from home."""
    row = rows.get("n95_mask") if profile.commute != "work_from_home" else None
    tag = next((c for c in ("two_wheelers", "metro_use") if c in factors), None)
    return _item(_COMMUTE_TEXT[profile.commute], _COMMUTE_WHY[profile.commute], row, tag)


def _add_context_items(factors: list[ContextFactor], routine: dict[str, list[PlanItem]]) -> None:
    """Make sure a relevant local factor is tagged in the routine (modifies ``routine``)."""
    if not factors:
        return

    def tagged(factor: ContextFactor) -> bool:
        return any(i.context_factor == factor for items in routine.values() for i in items)

    if not any(i.context_factor for items in routine.values() for i in items):
        text, why = FACTOR_ITEM[factors[0]]
        routine["midday"].append(_item(text, why, None, factors[0]))
    elif "biomass_cooking_heating" in factors and not tagged("biomass_cooking_heating"):
        text, why = FACTOR_ITEM["biomass_cooking_heating"]
        routine["morning"].append(_item(text, why, None, "biomass_cooking_heating"))


def build_fallback_plan(
    profile: HouseholdProfile, reading: AirReading, impact: ImpactResult
) -> Plan:
    """Construct a deterministic, schema-valid plan from AQI band and impact rows.

    Args:
        profile: Household profile for tailoring daily routines and commute actions.
        reading: AirReading providing AQI, CPCB band, and GRAP stage.
        impact: Evaluated impact result containing active impact table rows and exposure score.

    Returns:
        A fully-populated Plan model with routine slots, indoor hacks, and swaps.
    """
    rows = {r.id: r for r in impact.rows}
    band = reading.band
    factors = context_factors(profile, reading)
    why_band = _BAND_WHY[band]

    routine = {
        "morning": [_item(_BAND_MORNING[band], why_band)],
        "commute": [_commute_item(profile, rows, factors)],
        "midday": [_item(_BAND_MIDDAY[band], why_band)],
        "evening": [_item(_BAND_EVENING[band], why_band)],
    }
    _add_context_items(factors, routine)

    plan = Plan(
        routine=Routine(**routine),
        indoor_hacks=_rows_to_items(rows, _INDOOR_IDS, _INDOOR_DEFAULT)[:_MAX_LIST_ITEMS],
        swaps=_rows_to_items(rows, _SWAP_IDS, _SWAP_DEFAULT)[:_MAX_LIST_ITEMS],
        vulnerable_note=build_vulnerable_note(profile),
        impact_table=list(impact.rows),
        exposure_score=impact.exposure_score,
        fallback=True,
        estimated=reading.source == "estimated",
    )
    return Plan.model_validate(plan.model_dump())
