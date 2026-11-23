# AirWise Code Quality Improvement Plan

This document outlines targeted tasks to elevate the code quality score to 100 while maintaining 100% security, efficiency, testing, accessibility, and problem statement alignment.

---

## Phase 1: Domain Modeling & Internal Data Structures

- [x] **T1.1 Replace `_PM` Raw Tuple with `PMReading` NamedTuple**
  - **Target:** `airwise/services/aqi.py`
  - **Description:** Replace the untyped `_PM = tuple[float | None, float | None, str | None]` with a dedicated, immutable `class PMReading(NamedTuple): pm2_5: float | None; pm10: float | None; observed_at: str | None`.
  - **Details:**
    - Update `_fetch_pm_upstream()` to return `PMReading`.
    - Update `fetch_pm()` and the `_pm_readings` TTL cache to store `PMReading`.
    - Update `get_reading()` to access named attributes (`.pm2_5`, `.pm10`, `.observed_at`) instead of tuple indexing.
  - **Verification:** `pytest tests/test_aqi_service.py tests/test_aqi_cache.py`

---

## Phase 2: Schema Self-Documentation & Pydantic Enhancements

- [x] **T2.1 Add Comprehensive `Field(description=...)` to Pydantic Models**
  - **Target:** `airwise/models.py`
  - **Description:** Provide explicit descriptions on all fields across public API models to enable rich, self-documenting OpenAPI schemas.
  - **Models to Update:**
    - `AirReading`
    - `HouseholdProfile`
    - `ImpactFigures` / `ImpactRow`
    - `PlanItem` / `Routine` / `Plan`
    - `PlanRequest` / `PlanResponse`
    - `ChatTurn` / `ChatRequest` / `ChatReply` / `LLMChat`
  - **Verification:** `mypy airwise` and `pytest tests/test_plan_roundtrip.py tests/test_profile_roundtrip.py`

---

## Phase 3: Observability & Fallback Diagnostics

- [x] **T3.1 Add Structured Warning Logging on LLM Plan Fallback**
  - **Target:** `airwise/services/plan.py`
  - **Description:** When `generate_plan` catches an exception during LLM execution or JSON parsing, log the exception class name with structured logging without leaking user or prompt details.
  - **Implementation:**
    ```python
    except Exception as exc:
        logger.warning(
            "Plan generation fell back to deterministic rules: %s",
            type(exc).__name__,
            extra={"error_type": type(exc).__name__},
        )
        return build_fallback_plan(profile, reading, impact)
    ```
  - **Verification:** `pytest tests/test_plan_llm_outcomes.py`

---

## Phase 4: Full Validation & Quality Gate

- [x] **T4.1 Static Analysis and Linting**
  - Run `ruff check .`
  - Run `ruff format --check .`
  - Run `mypy airwise` (verifying strict mode compliance)
- [x] **T4.2 Test Suite Execution & Coverage**
  - Run `pytest -m "not browser" --cov=airwise --cov-report=term-missing` (verify >= 97% branch and statement coverage)
  - Run `pytest` (all 440 unit, integration, and browser tests)
- [x] **T4.3 Dependency Security Audit**
  - Run `pip-audit -r requirements-dev.lock --require-hashes --strict`
