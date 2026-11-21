"""Pydantic data models for AirWise."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CPCBBand = Literal["Good", "Satisfactory", "Moderate", "Poor", "Very Poor", "Severe"]
GrapStage = Literal["none", "Stage I", "Stage II", "Stage III", "Stage IV"]


class AirReading(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location_name: str = Field(min_length=1, max_length=100)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    pm2_5: float | None = Field(default=None, ge=0, le=5000)
    pm10: float | None = Field(default=None, ge=0, le=5000)
    aqi: int = Field(ge=0, le=500)
    band: CPCBBand
    grap_stage: GrapStage
    source: Literal["live", "estimated"]
    source_url: str | None = Field(default=None, max_length=200)
    observed_at: str | None = Field(default=None, max_length=32)  # UTC ISO 8601, live data only


Commute = Literal["car", "two_wheeler", "bus_metro", "walk_cycle", "work_from_home"]
CookFuel = Literal["lpg", "png", "induction", "biomass"]
Heating = Literal["none", "electric", "biomass_burning"]
Ventilation = Literal["open_often", "sometimes", "mostly_closed"]


class HouseholdProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    city: str = Field(min_length=1, max_length=100)
    kids: bool
    elderly: bool
    respiratory: bool
    commute: Commute
    cooking_fuel: CookFuel
    heating: Heating
    has_purifier: bool
    ventilation: Ventilation


class ImpactFigures(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exposure_reduction_pct: float = Field(ge=0, le=100)
    co2_kg_per_day: float = Field(ge=0, le=100)
    approximate: Literal[True] = True


class ImpactRow(ImpactFigures):
    id: str = Field(min_length=1, max_length=64)
    action: str = Field(min_length=1, max_length=200)
    basis: str = Field(min_length=1, max_length=200)
    source_note: str = Field(min_length=1, max_length=200)

    def figures(self) -> ImpactFigures:
        """The numeric figures of this row, without the descriptive fields."""
        return ImpactFigures(
            exposure_reduction_pct=self.exposure_reduction_pct,
            co2_kg_per_day=self.co2_kg_per_day,
        )


ContextFactor = Literal[
    "stubble_burning", "firecrackers", "biomass_cooking_heating", "two_wheelers", "metro_use"
]


class PlanItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=300)
    why_it_matters: str = Field(min_length=1, max_length=300)
    impact_id: str | None = Field(default=None, max_length=64)
    context_factor: ContextFactor | None = None
    impact: ImpactFigures | None = None


class Routine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    morning: list[PlanItem] = Field(min_length=1, max_length=3)
    commute: list[PlanItem] = Field(min_length=1, max_length=3)
    midday: list[PlanItem] = Field(min_length=1, max_length=3)
    evening: list[PlanItem] = Field(min_length=1, max_length=3)


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    routine: Routine
    indoor_hacks: list[PlanItem] = Field(min_length=1, max_length=5)
    swaps: list[PlanItem] = Field(min_length=1, max_length=5)
    vulnerable_note: str = Field(max_length=500)
    impact_table: list[ImpactRow] = Field(max_length=15)
    exposure_score: float = Field(ge=0, le=100)
    fallback: bool
    estimated: bool


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: HouseholdProfile
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def _both_or_neither(self) -> PlanRequest:
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together")
        return self


class PlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: Plan
    reading: AirReading


class LLMItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=300)
    why_it_matters: str = Field(min_length=1, max_length=300)
    impact_id: str | None = Field(default=None, max_length=2000)
    context_factor: ContextFactor | None = None


class LLMRoutine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    morning: list[LLMItem] = Field(min_length=1, max_length=3)
    commute: list[LLMItem] = Field(min_length=1, max_length=3)
    midday: list[LLMItem] = Field(min_length=1, max_length=3)
    evening: list[LLMItem] = Field(min_length=1, max_length=3)


class LLMPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    routine: LLMRoutine
    indoor_hacks: list[LLMItem] = Field(min_length=1, max_length=5)
    swaps: list[LLMItem] = Field(min_length=1, max_length=5)
    vulnerable_note: str = Field(max_length=500)


class ChatTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    message: str = Field(min_length=1, max_length=500)
    history: list[ChatTurn] = Field(default_factory=list, max_length=10)
    plan: Plan
    reading: AirReading
    profile: HouseholdProfile


class ChatReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reply: str = Field(max_length=2000)
    failed: bool = False


class LLMChat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reply: str = Field(min_length=1, max_length=2000)
    on_topic: bool
    discusses_health: bool
