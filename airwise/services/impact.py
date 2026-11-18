"""Impact_Engine: deterministic Impact_Table and Exposure_Score from a fixed rules table.

No randomness, clock, or I/O. All figures are approximate and illustrative.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from pydantic import ValidationError

from airwise.errors import InvalidInput
from airwise.models import AirReading, HouseholdProfile, ImpactRow

_NOTE = "Illustrative estimate informed by public CPCB and WHO guidance."


@dataclass(frozen=True)
class Rule:
    id: str
    applies: Callable[[HouseholdProfile, AirReading], bool]
    pct: Callable[[HouseholdProfile, AirReading], float]
    co2: Callable[[HouseholdProfile, AirReading], float]
    action: str
    basis: str
    source_note: str


@dataclass(frozen=True)
class ImpactResult:
    rows: list[ImpactRow]
    exposure_score: float


def _vulnerable(p: HouseholdProfile) -> bool:
    return p.kids or p.elderly or p.respiratory


def _zero(p: HouseholdProfile, r: AirReading) -> float:
    return 0.0


RULES: tuple[Rule, ...] = (
    Rule(
        id="n95_mask",
        applies=lambda p, r: r.aqi >= 101,
        pct=lambda p, r: 20.0 if _vulnerable(p) else 15.0,
        co2=_zero,
        action="Wear a well-fitted N95 mask outdoors when air quality is poor.",
        basis="Base 15% exposure cut outdoors, plus 5% if kids, elderly, or respiratory needs.",
        source_note=_NOTE,
    ),
    Rule(
        id="purifier_or_diy",
        applies=lambda p, r: not p.has_purifier,
        pct=lambda p, r: 25.0,
        co2=_zero,
        action="Run a purifier or a DIY Corsi-Rosenthal box in the room you use most.",
        basis="Assumes about 25% lower indoor exposure from filtering a main living space.",
        source_note=_NOTE,
    ),
    Rule(
        id="close_windows_peak",
        applies=lambda p, r: p.ventilation in ("open_often", "sometimes") and r.aqi >= 201,
        pct=lambda p, r: 10.0 if p.ventilation == "open_often" else 5.0,
        co2=_zero,
        action="Keep windows closed during peak pollution hours.",
        basis="10% cut if windows are often open, 5% if sometimes open; applies at AQI 201+.",
        source_note=_NOTE,
    ),
    Rule(
        id="wet_cleaning",
        applies=lambda p, r: r.aqi >= 101,
        pct=lambda p, r: 5.0,
        co2=_zero,
        action="Clean with a damp cloth or wet mop instead of dry sweeping.",
        basis="Assumes about 5% lower indoor dust exposure from avoiding resuspension.",
        source_note=_NOTE,
    ),
    Rule(
        id="clean_cooking",
        applies=lambda p, r: p.cooking_fuel == "biomass",
        pct=lambda p, r: 30.0,
        co2=lambda p, r: 1.5,
        action="Switch from biomass to LPG, PNG, or induction cooking.",
        basis="Assumes about 30% lower exposure and about 1.5 kg CO2 per day avoided.",
        source_note=_NOTE,
    ),
    Rule(
        id="biomass_heating_switch",
        applies=lambda p, r: p.heating == "biomass_burning",
        pct=lambda p, r: 25.0,
        co2=lambda p, r: 2.0,
        action="Replace biomass burning for heating with electric heating.",
        basis="Assumes about 25% lower exposure and about 2.0 kg CO2 per day avoided.",
        source_note=_NOTE,
    ),
    Rule(
        id="transit_swap",
        applies=lambda p, r: p.commute in ("car", "two_wheeler"),
        pct=lambda p, r: 8.0 if p.commute == "car" else 6.0,
        co2=lambda p, r: 3.0 if p.commute == "car" else 1.2,
        action="Swap some trips to bus or metro.",
        basis="Car round trip about 20 km at roughly 0.15 kg CO2 per km; two-wheeler about 1.2 kg.",
        source_note=_NOTE,
    ),
    Rule(
        id="carpool",
        applies=lambda p, r: p.commute == "car",
        pct=lambda p, r: 3.0,
        co2=lambda p, r: 1.5,
        action="Carpool with a colleague or neighbour.",
        basis="Assumes sharing a car halves emissions of a 20 km round trip at 0.15 kg CO2 per km.",
        source_note=_NOTE,
    ),
    Rule(
        id="no_burning_pledge",
        applies=lambda p, r: (
            r.aqi >= 201 or p.cooking_fuel == "biomass" or p.heating == "biomass_burning"
        ),
        pct=lambda p, r: 5.0,
        co2=lambda p, r: 0.5,
        action="Do not burn waste, leaves, or firecrackers near your home.",
        basis="Assumes about 5% lower local exposure and about 0.5 kg CO2 per day avoided.",
        source_note=_NOTE,
    ),
)


def combine(pcts: Iterable[float], cap: float = 100.0) -> float:
    """Combine reductions as 1 - prod(1 - p/100), rounded to 1 decimal, never above sum or cap."""
    values = list(pcts)
    remaining = 1.0
    for p in values:
        remaining *= 1.0 - p / 100.0
    score = round(100.0 * (1.0 - remaining), 1)
    return max(0.0, min(score, sum(values), cap))


def _validate(profile: object, reading: object) -> None:
    if profile is None or not isinstance(profile, HouseholdProfile):
        raise InvalidInput("profile")
    if reading is None or not isinstance(reading, AirReading):
        raise InvalidInput("reading")
    try:
        HouseholdProfile.model_validate(profile.model_dump())
    except ValidationError as exc:
        loc = exc.errors()[0]["loc"]
        raise InvalidInput(str(loc[0]) if loc else "profile") from exc
    try:
        AirReading.model_validate(reading.model_dump())
    except ValidationError as exc:
        loc = exc.errors()[0]["loc"]
        raise InvalidInput(str(loc[0]) if loc else "reading") from exc


def compute_impact(profile: HouseholdProfile, reading: AirReading) -> ImpactResult:
    _validate(profile, reading)
    rows: list[ImpactRow] = []
    for rule in RULES:
        if not rule.applies(profile, reading):
            continue
        rows.append(
            ImpactRow(
                id=rule.id,
                action=rule.action,
                basis=rule.basis,
                source_note=rule.source_note,
                exposure_reduction_pct=rule.pct(profile, reading),
                co2_kg_per_day=rule.co2(profile, reading),
                approximate=True,
            )
        )
    return ImpactResult(rows=rows, exposure_score=combine(r.exposure_reduction_pct for r in rows))
