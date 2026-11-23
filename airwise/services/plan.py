"""Plan_Generator: one LLM call for wording, server-owned figures, deterministic fallback."""

from __future__ import annotations

import logging
from typing import Any

from airwise.config import Deadline, anthropic_api_key
from airwise.models import (
    AirReading,
    HouseholdProfile,
    ImpactRow,
    LLMItem,
    LLMPlan,
    Plan,
    PlanItem,
)
from airwise.services.fallback import (
    FACTOR_ITEM,
    build_fallback_plan,
    build_vulnerable_note,
    context_factors,
)
from airwise.services.impact import ImpactResult, compute_impact
from airwise.services.llm import (
    PLAN_JSON_SCHEMA,
    LLMClient,
    build_plan_user_prompt,
    build_system_prompt,
)

logger = logging.getLogger("airwise")

_NOTE_MAX = 500
_SLOTS = ("morning", "commute", "midday", "evening")
_MAX_SLOT_ITEMS = 3


def _sanitize_item(item: LLMItem, rows: dict[str, ImpactRow]) -> PlanItem:
    row = rows.get(item.impact_id) if item.impact_id is not None else None
    return PlanItem(
        text=item.text,
        why_it_matters=item.why_it_matters,
        impact_id=row.id if row else None,
        context_factor=item.context_factor,
        impact=row.figures() if row else None,
    )


def sanitize(llm_plan: LLMPlan, impact: ImpactResult) -> dict[str, Any]:
    """Unknown impact_id becomes None; figures are copied from the table only."""
    rows = {r.id: r for r in impact.rows}

    def conv(items: list[LLMItem]) -> list[PlanItem]:
        return [_sanitize_item(i, rows) for i in items]

    return {
        "routine": {slot: conv(getattr(llm_plan.routine, slot)) for slot in _SLOTS},
        "indoor_hacks": conv(llm_plan.indoor_hacks),
        "swaps": conv(llm_plan.swaps),
        "vulnerable_note": llm_plan.vulnerable_note,
    }


def _missing_groups(profile: HouseholdProfile, note: str) -> bool:
    lowered = note.lower()
    checks = (
        (profile.kids, "kids"),
        (profile.elderly, "elderly"),
        (profile.respiratory, "respiratory"),
    )
    return any(present and word not in lowered for present, word in checks)


def ensure_vulnerable_note(profile: HouseholdProfile, note: str) -> str:
    """Make sure the note names every vulnerable group present (at most 500 chars)."""
    if not (profile.kids or profile.elderly or profile.respiratory):
        return note[:_NOTE_MAX]
    if note.strip() and not _missing_groups(profile, note):
        return note[:_NOTE_MAX]
    sentence = build_vulnerable_note(profile)
    base = note.strip()
    if not base:
        return sentence[:_NOTE_MAX]
    room = _NOTE_MAX - len(sentence) - 1
    if room <= 0:
        return sentence[:_NOTE_MAX]
    return f"{base[:room].rstrip()} {sentence}"[:_NOTE_MAX]


def ensure_local_context(
    profile: HouseholdProfile, reading: AirReading, routine: dict[str, list[PlanItem]]
) -> None:
    """Add a routine item for the first relevant local factor if none is tagged (in place)."""
    factors = context_factors(profile, reading)
    if not factors:
        return
    if any(i.context_factor in factors for slot in _SLOTS for i in routine[slot]):
        return
    factor = factors[0]
    text, why = FACTOR_ITEM[factor]
    new_item = PlanItem(text=text[:300], why_it_matters=why[:300], context_factor=factor)
    for slot in ("midday", "morning", "evening", "commute"):
        if len(routine[slot]) < _MAX_SLOT_ITEMS:
            routine[slot].append(new_item)
            return
    routine["midday"][-1] = new_item


async def generate_plan(
    profile: HouseholdProfile,
    reading: AirReading,
    *,
    llm: LLMClient,
    deadline: Deadline,
) -> Plan:
    """Return the plan: LLM wording over server-owned figures, or the deterministic fallback."""
    impact = compute_impact(profile, reading)
    if not anthropic_api_key() or deadline.should_skip_llm():
        return build_fallback_plan(profile, reading, impact)

    try:
        raw = await llm.complete_json(
            system=build_system_prompt(),
            user=build_plan_user_prompt(profile, reading, impact.rows),
            schema_name="airwise_plan",
            schema=PLAN_JSON_SCHEMA,
            timeout_s=deadline.llm_timeout(),
        )
        llm_plan = LLMPlan.model_validate(raw)
        parts = sanitize(llm_plan, impact)
        parts["vulnerable_note"] = ensure_vulnerable_note(profile, parts["vulnerable_note"])
        ensure_local_context(profile, reading, parts["routine"])
        return Plan(
            routine=parts["routine"],
            indoor_hacks=parts["indoor_hacks"],
            swaps=parts["swaps"],
            vulnerable_note=parts["vulnerable_note"],
            impact_table=list(impact.rows),
            exposure_score=impact.exposure_score,
            fallback=False,
            estimated=reading.source == "estimated",
        )
    # Deliberately broad: any LLM error, timeout, or invalid output means fallback.
    except Exception as exc:
        # Log only the class: the message can echo prompt or provider response text.
        logger.warning(
            "Plan generation fell back to deterministic rules: %s",
            type(exc).__name__,
            extra={"error_type": type(exc).__name__},
        )
        return build_fallback_plan(profile, reading, impact)
