"""Fallback_Plan builder: a deterministic, schema-valid Plan from the Impact_Table.

Pure function: no LLM, no I/O, no clock.
"""
from __future__ import annotations

from airwise.models import (
    AirReading,
    HouseholdProfile,
    ImpactFigures,
    ImpactRow,
    Plan,
    PlanItem,
)
from airwise.services.impact import ImpactResult

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
    "bus_metro": "Shared transport lowers emissions per person, and a mask lowers exposure in crowds.",
    "walk_cycle": "Streets away from traffic have lower concentrations of pollutants.",
    "work_from_home": "Staying home avoids the outdoor exposure of a commute.",
}


def _figures(row: ImpactRow | None) -> ImpactFigures | None:
    if row is None:
        return None
    return ImpactFigures(
        exposure_reduction_pct=row.exposure_reduction_pct,
        co2_kg_per_day=row.co2_kg_per_day,
        approximate=True,
    )


def _item(
    text: str,
    why: str,
    row: ImpactRow | None = None,
    context_factor: str | None = None,
) -> PlanItem:
    return PlanItem(
        text=text[:300],
        why_it_matters=(why or "Helps reduce your exposure to polluted air.")[:300],
        impact_id=row.id if row else None,
        context_factor=context_factor,  # type: ignore[arg-type]
        impact=_figures(row),
    )


def _vulnerable_note(profile: HouseholdProfile) -> str:
    groups = []
    if profile.kids:
        groups.append("kids")
    if profile.elderly:
        groups.append("elderly members")
    if profile.respiratory:
        groups.append("members with respiratory conditions")
    if not groups:
        return "No kids, elderly, or respiratory-sensitive members were listed; normal precautions apply."
    names = ", ".join(groups)
    note = (
        f"Take extra care for {names}: keep them indoors on high-pollution days, "
        "use a purifier in their room, and consult a doctor if symptoms such as "
        "coughing, wheezing, or breathlessness appear."
    )
    return note[:500]


def _context_factors(profile: HouseholdProfile, reading: AirReading) -> list[str]:
    factors: list[str] = []
    if profile.cooking_fuel == "biomass" or profile.heating == "biomass_burning":
        factors.append("biomass_cooking_heating")
    if profile.commute == "two_wheeler":
        factors.append("two_wheelers")
    if profile.commute == "bus_metro":
        factors.append("metro_use")
    if reading.aqi >= 201:
        factors.append("stubble_burning")
        factors.append("firecrackers")
    return factors


_FACTOR_ITEM = {
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
        "Check smoke forecasts: crop-residue (stubble) burning season can worsen air; stay indoors on smoky days.",
        "Stubble smoke drifting into cities adds fine particles on top of local pollution.",
    ),
    "firecrackers": (
        "Avoid firecrackers and stay away from areas where they are burnt, especially around festivals.",
        "Firecracker smoke sharply raises short-term fine particle levels.",
    ),
}


def build_fallback_plan(
    profile: HouseholdProfile, reading: AirReading, impact: ImpactResult
) -> Plan:
    rows = {r.id: r for r in impact.rows}
    band = reading.band
    factors = _context_factors(profile, reading)
    why_band = _BAND_WHY[band]

    def tag_for(*candidates: str) -> str | None:
        for c in candidates:
            if c in factors:
                return c
        return None

    # Routine
    morning = [_item(_BAND_MORNING[band], why_band)]
    commute_row = rows.get("n95_mask") if profile.commute != "work_from_home" else None
    commute_tag = tag_for("two_wheelers", "metro_use")
    commute = [
        _item(
            _COMMUTE_TEXT[profile.commute],
            _COMMUTE_WHY[profile.commute],
            commute_row,
            commute_tag,
        )
    ]
    midday = [_item(_BAND_MIDDAY[band], why_band)]
    evening = [_item(_BAND_EVENING[band], why_band)]

    # Ensure at least one routine item carries a relevant context tag.
    routine_lists = {"morning": morning, "commute": commute, "midday": midday, "evening": evening}
    if factors and not any(i.context_factor for lst in routine_lists.values() for i in lst):
        f = factors[0]
        text, why = _FACTOR_ITEM[f]
        midday.append(_item(text, why, None, f))
    elif factors:
        # Add a biomass/seasonal tagged item when available to reflect profile/reading.
        for f in factors:
            if f in ("biomass_cooking_heating",) and not any(
                i.context_factor == f for lst in routine_lists.values() for i in lst
            ):
                text, why = _FACTOR_ITEM[f]
                morning.append(_item(text, why, None, f))
                break

    # Indoor hacks
    indoor: list[PlanItem] = []
    for rid in _INDOOR_IDS:
        row = rows.get(rid)
        if row is not None:
            indoor.append(_item(row.action, row.basis, row))
    if not indoor:
        indoor.append(
            _item(
                "Keep indoor air clean: avoid smoke, incense, and dry sweeping.",
                "Indoor sources add to pollution you breathe even when outdoor air is fine.",
            )
        )

    # Swaps
    swaps: list[PlanItem] = []
    for rid in _SWAP_IDS:
        row = rows.get(rid)
        if row is not None:
            swaps.append(_item(row.action, row.basis, row))
    if not swaps:
        swaps.append(
            _item(
                "Walk, cycle, or use public transport for short trips when you can.",
                "Fewer fuel-burning trips cut both local pollution and CO2 emissions.",
            )
        )

    plan = Plan(
        routine={"morning": morning, "commute": commute, "midday": midday, "evening": evening},  # type: ignore[arg-type]
        indoor_hacks=indoor[:5],
        swaps=swaps[:5],
        vulnerable_note=_vulnerable_note(profile),
        impact_table=list(impact.rows),
        exposure_score=impact.exposure_score,
        fallback=True,
        estimated=reading.source == "estimated",
    )
    return Plan.model_validate(plan.model_dump())
