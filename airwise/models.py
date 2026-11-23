"""Pydantic data models for AirWise."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CPCBBand = Literal["Good", "Satisfactory", "Moderate", "Poor", "Very Poor", "Severe"]
GrapStage = Literal["none", "Stage I", "Stage II", "Stage III", "Stage IV"]


class AirReading(BaseModel):
    """Current air quality for a location, from live data or an estimate."""

    model_config = ConfigDict(extra="forbid")

    location_name: str = Field(
        min_length=1, max_length=100, description="Display name of the resolved location."
    )
    latitude: float = Field(ge=-90, le=90, description="Latitude in decimal degrees.")
    longitude: float = Field(ge=-180, le=180, description="Longitude in decimal degrees.")
    pm2_5: float | None = Field(
        default=None, ge=0, le=5000, description="PM2.5 concentration in µg/m³, if available."
    )
    pm10: float | None = Field(
        default=None, ge=0, le=5000, description="PM10 concentration in µg/m³, if available."
    )
    aqi: int = Field(ge=0, le=500, description="CPCB India Air Quality Index (0-500).")
    band: CPCBBand = Field(description="CPCB AQI category for the index value.")
    grap_stage: GrapStage = Field(
        description="Indicative Graded Response Action Plan (GRAP) stage for the index value."
    )
    source: Literal["live", "estimated"] = Field(
        description="Whether the values are live upstream data or a typical-value estimate."
    )
    source_url: str | None = Field(
        default=None, max_length=200, description="Link to the data source (live data only)."
    )
    observed_at: str | None = Field(
        default=None,
        max_length=32,
        description="Observation time in UTC ISO 8601 (live data only).",
    )


Commute = Literal["car", "two_wheeler", "bus_metro", "walk_cycle", "work_from_home"]
CookFuel = Literal["lpg", "png", "induction", "biomass"]
Heating = Literal["none", "electric", "biomass_burning"]
Ventilation = Literal["open_often", "sometimes", "mostly_closed"]


class HouseholdProfile(BaseModel):
    """Household details the plan is tailored to."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    city: str = Field(
        min_length=1, max_length=100, description="Indian city the household lives in."
    )
    kids: bool = Field(description="Whether children live in the household.")
    elderly: bool = Field(description="Whether elderly people live in the household.")
    respiratory: bool = Field(
        description="Whether anyone in the household has a respiratory condition."
    )
    commute: Commute = Field(description="Main commute mode.")
    cooking_fuel: CookFuel = Field(description="Main cooking fuel.")
    heating: Heating = Field(description="Winter heating method.")
    has_purifier: bool = Field(description="Whether the household owns an air purifier.")
    ventilation: Ventilation = Field(description="How often windows are kept open at home.")


class ImpactFigures(BaseModel):
    """Approximate exposure and CO2 figures for one action."""

    model_config = ConfigDict(extra="forbid")

    exposure_reduction_pct: float = Field(
        ge=0, le=100, description="Approximate reduction in pollution exposure, in percent."
    )
    co2_kg_per_day: float = Field(
        ge=0, le=100, description="Approximate CO2 avoided per day, in kilograms."
    )
    approximate: Literal[True] = Field(
        default=True, description="Always true: figures are indicative estimates, not measurements."
    )


class ImpactRow(ImpactFigures):
    """One row of the impact table: an action with its figures and basis."""

    id: str = Field(min_length=1, max_length=64, description="Stable identifier of the action.")
    action: str = Field(min_length=1, max_length=200, description="The action being quantified.")
    basis: str = Field(
        min_length=1, max_length=200, description="Assumption the figures are based on."
    )
    source_note: str = Field(
        min_length=1, max_length=200, description="Where the figures come from."
    )

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
    """A single recommendation, optionally tied to an impact row or local factor."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=300, description="The recommended action.")
    why_it_matters: str = Field(
        min_length=1, max_length=300, description="Short reason the action helps."
    )
    impact_id: str | None = Field(
        default=None,
        max_length=64,
        description="Identifier of the impact table row this item refers to, if any.",
    )
    context_factor: ContextFactor | None = Field(
        default=None, description="Local pollution factor this item relates to, if any."
    )
    impact: ImpactFigures | None = Field(
        default=None, description="Figures copied from the referenced impact row, if any."
    )


class Routine(BaseModel):
    """Recommendations for each part of the day."""

    model_config = ConfigDict(extra="forbid")

    morning: list[PlanItem] = Field(
        min_length=1, max_length=3, description="Recommendations for the morning."
    )
    commute: list[PlanItem] = Field(
        min_length=1, max_length=3, description="Recommendations for the commute."
    )
    midday: list[PlanItem] = Field(
        min_length=1, max_length=3, description="Recommendations for midday."
    )
    evening: list[PlanItem] = Field(
        min_length=1, max_length=3, description="Recommendations for the evening."
    )


class Plan(BaseModel):
    """The full plan returned to the client."""

    model_config = ConfigDict(extra="forbid")

    routine: Routine = Field(description="Recommendations for each part of the day.")
    indoor_hacks: list[PlanItem] = Field(
        min_length=1, max_length=5, description="Tips for cleaner indoor air."
    )
    swaps: list[PlanItem] = Field(
        min_length=1, max_length=5, description="Habit swaps that reduce exposure or emissions."
    )
    vulnerable_note: str = Field(
        max_length=500,
        description="Extra guidance for children, elderly or respiratory patients (may be empty).",
    )
    impact_table: list[ImpactRow] = Field(
        max_length=15, description="Impact rows applicable to this household and reading."
    )
    exposure_score: float = Field(
        ge=0,
        le=100,
        description="Combined approximate exposure reduction of the impact table, in percent.",
    )
    fallback: bool = Field(
        description="True when the plan came from deterministic rules instead of the LLM."
    )
    estimated: bool = Field(
        description="True when the plan is based on an estimated rather than live reading."
    )


class PlanRequest(BaseModel):
    """Request body for plan generation: a profile and optional coordinates."""

    model_config = ConfigDict(extra="forbid")

    profile: HouseholdProfile = Field(description="Household details to tailor the plan to.")
    latitude: float | None = Field(
        default=None,
        ge=-90,
        le=90,
        description="Device latitude; must be sent together with longitude.",
    )
    longitude: float | None = Field(
        default=None,
        ge=-180,
        le=180,
        description="Device longitude; must be sent together with latitude.",
    )

    @model_validator(mode="after")
    def _both_or_neither(self) -> PlanRequest:
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together")
        return self


class PlanResponse(BaseModel):
    """A plan together with the air reading it was based on."""

    model_config = ConfigDict(extra="forbid")

    plan: Plan = Field(description="The generated plan.")
    reading: AirReading = Field(description="The air reading the plan was based on.")


class LLMItem(BaseModel):
    """A recommendation as written by the LLM, before figures are attached."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=300, description="The recommended action.")
    why_it_matters: str = Field(
        min_length=1, max_length=300, description="Short reason the action helps."
    )
    impact_id: str | None = Field(
        default=None,
        max_length=2000,
        description="Impact table row cited by the LLM; unknown ids are discarded later.",
    )
    context_factor: ContextFactor | None = Field(
        default=None, description="Local pollution factor this item relates to, if any."
    )


class LLMRoutine(BaseModel):
    """LLM-written routine, one list of items per part of the day."""

    model_config = ConfigDict(extra="forbid")

    morning: list[LLMItem] = Field(
        min_length=1, max_length=3, description="Recommendations for the morning."
    )
    commute: list[LLMItem] = Field(
        min_length=1, max_length=3, description="Recommendations for the commute."
    )
    midday: list[LLMItem] = Field(
        min_length=1, max_length=3, description="Recommendations for midday."
    )
    evening: list[LLMItem] = Field(
        min_length=1, max_length=3, description="Recommendations for the evening."
    )


class LLMPlan(BaseModel):
    """Structured plan wording as returned by the LLM."""

    model_config = ConfigDict(extra="forbid")

    routine: LLMRoutine = Field(description="Recommendations for each part of the day.")
    indoor_hacks: list[LLMItem] = Field(
        min_length=1, max_length=5, description="Tips for cleaner indoor air."
    )
    swaps: list[LLMItem] = Field(
        min_length=1, max_length=5, description="Habit swaps that reduce exposure or emissions."
    )
    vulnerable_note: str = Field(
        max_length=500,
        description="Extra guidance for children, elderly or respiratory patients (may be empty).",
    )


class ChatTurn(BaseModel):
    """One earlier message in a chat conversation."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"] = Field(description="Who wrote the message.")
    content: str = Field(min_length=1, max_length=2000, description="Message text.")


class ChatRequest(BaseModel):
    """Request body for chat: a message, history and the current plan context."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    message: str = Field(min_length=1, max_length=500, description="The user's new question.")
    history: list[ChatTurn] = Field(
        default_factory=list, max_length=10, description="Earlier turns, oldest first."
    )
    plan: Plan = Field(description="The plan the conversation is about.")
    reading: AirReading = Field(description="The air reading the plan was based on.")
    profile: HouseholdProfile = Field(description="The household the plan was made for.")


class ChatReply(BaseModel):
    """Reply returned to the chat client."""

    model_config = ConfigDict(extra="forbid")

    reply: str = Field(max_length=2000, description="The assistant's answer.")
    failed: bool = Field(
        default=False, description="True when the answer could not be generated (service error)."
    )


class LLMChat(BaseModel):
    """Structured chat answer as returned by the LLM."""

    model_config = ConfigDict(extra="forbid")

    reply: str = Field(min_length=1, max_length=2000, description="The assistant's answer.")
    on_topic: bool = Field(
        description="Whether the message concerns air quality, the plan or household exposure."
    )
    discusses_health: bool = Field(
        description="Whether the reply gives health-related content needing a disclaimer."
    )
