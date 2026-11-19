# Implementation Plan: AirWise

## Overview

The plan follows the component layout in the design: a FastAPI app in `airwise/` exposed through `api/index.py`, a single static page in `public/index.html`, and pytest plus Hypothesis tests in `tests/`. Language: Python 3 for the backend, vanilla JavaScript for the page. Each top-level task ends in something demoable (for example `GET /api/health`, `GET /api/aqi`, `POST /api/plan`, the working page, then chat). Property tests are sub-tasks tagged with the design's property numbers. Every property test file carries the comment `# Feature: airwise, Property N: <title>` and uses `@settings(max_examples=100)` or more.

Some scaffold files may already exist from an earlier draft (`pyproject.toml`, `vercel.json`, `.env.example`, `.gitignore`, and possibly `airwise/models.py` and `airwise/services/aqi.py`). Tasks review and align existing files with the approved design instead of assuming a blank workspace. Do not overwrite working content without reading it first.

## Tasks

- [x] 1. Project skeleton with a working health endpoint
  - [x] 1.1 Review and align the scaffold and verify the environment
    - Read the existing `pyproject.toml`, `vercel.json`, `.env.example`, and `.gitignore`. Align them with the design instead of recreating them.
    - `pyproject.toml`: runtime dependencies `fastapi`, `httpx`, `pydantic`; `dev` extra `pytest>=8.0`, `uvicorn>=0.29`, `hypothesis>=6.100`; a `[tool.pytest.ini_options]` section with `testpaths = ["tests"]`. Do not create `requirements.txt`.
    - `vercel.json`: rewrite `/api/(.*)` to `/api/index`, `functions."api/index.py".maxDuration` of 30, `includeFiles` of `public/**`.
    - `.env.example`: names `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, and `LLM_MODEL` with empty or placeholder values and no real credential.
    - `.gitignore`: exclude `.env`, virtual environments, `__pycache__`, `.pytest_cache`, `.hypothesis`, and `.vercel`.
    - Verify installation: create a virtual environment and run `pip install -e ".[dev]"`. Local Python is 3.15 and some packages (for example `pydantic-core`) may lack wheels. If installation fails, recreate the environment with Python 3.12 (for example `py -3.12 -m venv .venv`), reinstall, and record the working version in a `requires-python` bound in `pyproject.toml` and in the README task later.
    - Confirm `import fastapi, httpx, pydantic, hypothesis` succeeds in the chosen environment.
    - _Requirements: 11.5, 12.3, 12.4, 12.8_

  - [x] 1.2 Create the app skeleton and health endpoint
    - Create `airwise/__init__.py`, `airwise/config.py` (constants and env readers from the design), `airwise/errors.py` (`AppError` hierarchy with status, code, fields), and `airwise/services/__init__.py`.
    - Create `airwise/main.py` with `create_app()`, `GET /api/health` returning `{"status": "ok"}`, `GET /` returning the contents of `public/index.html`, and exception handlers for `AppError` and `RequestValidationError` that produce the `{"error": {"code", "message", "fields"}}` body without echoing submitted values.
    - Create `api/index.py` with `from airwise.main import app`.
    - Create a placeholder `public/index.html` (title, heading, disclaimer text, no external resources).
    - Create `tests/__init__.py` (if needed) and `tests/conftest.py` with an autouse fixture that removes `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, and `LLM_MODEL` from the environment and patches `socket.socket.connect` to raise, plus a `client` fixture built from `create_app()`.
    - Demo: `uvicorn airwise.main:create_app --factory` serves `/api/health` and `/`.
    - _Requirements: 9.1, 11.6, 12.1, 12.2, 12.5, 13.2_

  - [x] 1.3 Write static repository checks and health test
    - `tests/test_static_repo.py`: `requirements.txt` does not exist, `.env.example` lists `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, and `LLM_MODEL` with no real key, `vercel.json` has the rewrite and `LLM_TIMEOUT_S + 2 <= maxDuration`, `pyproject.toml` declares the three runtime dependencies.
    - `tests/test_health.py`: `GET /api/health` returns 200 and `{"status": "ok"}`; `GET /` returns HTML.
    - _Requirements: 11.5, 12.3, 12.4, 12.8, 13.1_

- [x] 2. Location and AQI service with `GET /api/aqi`
  - [x] 2.1 Add AQI data models
    - In `airwise/models.py` (review it first if it exists), add `CPCBBand`, `GrapStage`, and `AirReading` with the ranges from the design (`extra="forbid"`, latitude -90..90, longitude -180..180, pm values 0..5000 or `None`, aqi 0..500, location name 1..100).
    - _Requirements: 1.3, 1.4, 1.5, 2.2, 9.4_

  - [x] 2.2 Implement the pure AQI functions
    - In `airwise/services/aqi.py` (review it first if it exists), add the CPCB breakpoint tables, `sub_index`, `compute_aqi` (maximum of available sub-indices, rounded, capped at 500, gap values clamped to the next range's low index), `band_for`, and `grap_for`.
    - _Requirements: 1.3, 1.4, 1.5, 1.6_

  - [x] 2.3 Write property test for AQI computation
    - **Property 1: AQI is the bounded maximum of sub-indices**
    - **Validates: Requirements 1.3**

  - [x] 2.4 Write property tests for band and GRAP mapping
    - **Property 2: Every AQI has exactly one CPCB band with correct boundaries**
    - **Validates: Requirements 1.4, 13.3**
    - **Property 3: GRAP stage mapping**
    - **Validates: Requirements 1.5, 1.6**
    - Add example tests for the reference points (PM2.5 of 60 gives 100, PM10 of 430 gives 400), single-pollutant input, and the 500 cap.

  - [x] 2.5 Implement geocoding, air quality fetch, and the resilient reading
    - In `airwise/services/aqi.py`, add `geocode`, `fetch_pm`, `get_reading`, and `estimated_reading` using an injected `httpx.AsyncClient`, 8 s timeouts, one attempt, `count=1` and `countryCode=IN`.
    - Validate and trim the city first and raise `InvalidCity` before any HTTP call. Add `CityNotFound`, `LookupUnavailable`, and `InvalidCity` to `errors.py`.
    - Any Air_Quality_API failure, timeout, bad JSON, or both values missing returns an estimated reading (`ESTIMATED_PM25`, `ESTIMATED_PM10`) with `source="estimated"`. At least one value present returns `source="live"`.
    - _Requirements: 1.1, 1.2, 1.8, 1.9, 1.10, 1.11, 3.1, 3.2, 3.5_

  - [x] 2.6 Write property test and mocked-HTTP tests for the AQI service
    - **Property 4: City name validation**
    - **Validates: Requirements 1.9**
    - `httpx.MockTransport` examples: request parameters, no `results` gives `CityNotFound` with zero AQ requests, geocoding timeout, 500, and transport error give `LookupUnavailable`, AQ timeout, 500, malformed JSON, and both-null each give an estimated reading, the AQ call is attempted once.
    - _Requirements: 1.1, 1.8, 1.10, 3.1, 3.2, 3.5_

  - [x] 2.7 Add `GET /api/aqi`
    - In `airwise/main.py`, add a dependency that provides the shared `httpx.AsyncClient` (overridable in tests) and the route. It requires exactly one of `city` or both `lat` and `lon`. Otherwise return 422 naming the fields. Map `CityNotFound` to 404 `city_not_found` and `LookupUnavailable` to 502 `lookup_unavailable`.
    - Demo: `GET /api/aqi?city=Delhi` returns an `AirReading`, live or estimated.
    - _Requirements: 1.1, 1.8, 1.9, 1.10, 2.2, 2.3_

  - [x] 2.8 Write property test and endpoint tests for coordinate validation
    - **Property 5: Coordinate validation**
    - **Validates: Requirements 2.3**
    - Endpoint tests with dependency overrides: valid city, valid coordinates, 404, 502, estimated fallback with HTTP 200, neither or mixed parameters give 422.
    - _Requirements: 2.2, 2.3, 3.1_

- [x] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Household profile and Impact_Engine
  - [x] 4.1 Add the profile and impact models
    - In `airwise/models.py`, add the `Commute`, `CookFuel`, `Heating`, and `Ventilation` literals, `HouseholdProfile` (city trimmed, 1..100), `ImpactFigures`, and `ImpactRow` with the constraints from the design.
    - Add `InvalidInput` to `errors.py`.
    - _Requirements: 4.1, 4.2, 4.3, 5.2, 5.3_

  - [x] 4.2 Write property test for the profile round trip
    - **Property 6: Household_Profile JSON round trip**
    - **Validates: Requirements 4.8**
    - Create `tests/strategies.py` with `profiles()` and `readings()` (built through the real `compute_aqi`, `band_for`, `grap_for`).

  - [x] 4.3 Implement the Impact_Engine
    - Create `airwise/services/impact.py` with the fixed-order `RULES` table from the design, `combine`, and `compute_impact` returning rows and `exposure_score`. No randomness, clock, or I/O.
    - Re-check inputs and raise `InvalidInput(field)` for a missing profile or reading or out-of-range values.
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9, 5.11, 5.12_

  - [x] 4.4 Write property test for engine determinism and row shape
    - **Property 9: Impact_Engine is deterministic and rows are well-formed**
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.5, 13.4**

  - [x] 4.5 Write property tests for conditional rows and score bounds
    - **Property 10: Conditional impact rows**
    - **Validates: Requirements 5.6, 5.7, 5.8, 5.9**
    - **Property 11: Exposure_Score combination bounds**
    - **Validates: Requirements 5.4, 5.12**

  - [x] 4.6 Write unit tests for the Impact_Engine
    - Clean-air profile gives 0 rows and score 0, worst-case profile gives 9 rows, invalid direct inputs raise `InvalidInput` and return nothing.
    - _Requirements: 5.11, 5.12, 13.1_

- [x] 5. Plan generation, fallback, and `POST /api/plan`
  - [x] 5.1 Add the plan models
    - In `airwise/models.py`, add `PlanItem`, `Routine`, `Plan`, `PlanRequest` (latitude and longitude both or neither), `PlanResponse`, and the LLM-facing `LLMItem` and `LLMPlan`. Enforce the 1..3, 1..5, 0..15 counts, 300 and 500 character caps, the 2,000 character and 50 item caps.
    - _Requirements: 6.2, 6.4, 6.12, 9.3, 9.4, 9.5_

  - [x] 5.2 Implement the LLM client and deadline helper
    - Create `airwise/services/llm.py` with the `LLMClient` protocol, `LLMUnavailable`, and `AnthropicClient` (`httpx` POST to `{ANTHROPIC_BASE_URL}/messages`, no retries, forced tool call with the schema as `input_schema`, `asyncio.wait_for`, key and model read from the environment at call time, no key in messages). Add `PLAN_JSON_SCHEMA` and the system and user prompt builders, with untrusted text passed inside a JSON object.
    - Add the pure `Deadline` helper (remaining time, planned LLM timeout `min(LLM_TIMEOUT_S, remaining - 1)`, skip when under `LLM_MIN_BUDGET_S`) to `airwise/config.py`.
    - _Requirements: 6.1, 6.2, 6.3, 6.10, 11.1, 11.2, 12.6, 12.7, 12.8_

  - [x] 5.3 Write property test for the time budget
    - **Property 22: LLM time budget stays inside the function limit**
    - **Validates: Requirements 12.6, 12.8**
    - Add example tests for `AnthropicClient` argument construction with `httpx.MockTransport`, and for the `claude-haiku-5-5` default when `LLM_MODEL` is unset or empty.
    - _Requirements: 6.10_

  - [x] 5.4 Implement the Fallback_Plan builder
    - Create `airwise/services/fallback.py` with `build_fallback_plan(profile, reading, impact)`: routine slots from templates keyed on band and commute, indoor hacks and swaps from applicable rows plus generic items, a vulnerable-members note naming each group, `why_it_matters` of 1..300 characters on every item, `context_factor` tags, `fallback=True`. Validate with `Plan.model_validate` inside the builder.
    - _Requirements: 6.4, 6.8, 6.9, 7.4, 7.6_

  - [x] 5.5 Write property test for the Fallback_Plan
    - **Property 14: Fallback_Plan is schema-valid and independent of the LLM**
    - **Validates: Requirements 7.6, 6.4**
    - Also write **Property 16: Plan JSON round trip** in `tests/test_plan_roundtrip.py`, with a `plans()` strategy in `tests/strategies.py`.
    - **Validates: Requirements 13.5**

  - [x] 5.6 Implement the Plan_Generator
    - Create `airwise/services/plan.py` with `generate_plan(profile, reading, *, llm, deadline)`: compute the impact, skip the LLM when the key is missing or the budget is under 2 s, make exactly one call with no retry, fall back on any error, timeout, or `ValidationError`, then `sanitize` (unknown `impact_id` becomes `None`, figures copied from the table), `ensure_vulnerable_note`, `ensure_local_context`, and set `estimated` from the reading source.
    - _Requirements: 3.4, 6.1, 6.5, 6.6, 6.7, 6.8, 6.9, 6.11, 7.1, 7.2, 7.3, 7.5, 7.8, 12.7_

  - [x] 5.7 Write property test for figure overwrite
    - **Property 12: Plan impact figures always equal table figures**
    - **Validates: Requirements 6.7**
    - Add an `llm_plans()` strategy that includes bogus `impact_id` values and extra numeric keys.

  - [x] 5.8 Write property test for LLM outcomes
    - **Property 13: LLM outcomes map to a valid Plan with at most one call**
    - **Validates: Requirements 6.1, 6.5, 6.6, 6.11, 7.1, 7.2, 7.3, 7.4, 7.5, 7.8, 12.7**
    - Use a fake `LLMClient` that counts calls and returns the generated outcome (valid, unparsable, schema-invalid, raised error, timeout) with the key present, empty, or unset.

  - [x] 5.9 Write property test for plan content guarantees
    - **Property 15: Plan content guarantees**
    - **Validates: Requirements 3.4, 6.8, 6.9**
    - Cover both the LLM path and the fallback path.

  - [x] 5.10 Add `POST /api/plan`
    - In `airwise/main.py`, add dependencies for the LLM client (overridable) and a per-request `Deadline` of `REQUEST_DEADLINE_S`. The route gets the reading from coordinates or city, calls `generate_plan`, and returns `PlanResponse`. Map errors to 404, 422, and 502.
    - Demo: with no key set, `POST /api/plan` returns a flagged Fallback_Plan; with a key it returns an LLM plan.
    - _Requirements: 1.1, 2.2, 3.4, 4.3, 6.12, 7.1, 12.6_

  - [x] 5.11 Write property test and endpoint tests for plan validation
    - **Property 7: Invalid payloads are rejected with the offending fields**
    - **Validates: Requirements 4.2, 4.3, 9.1, 9.3, 9.4, 9.5**
    - Cover `/api/plan` here. Chat is added in task 8.
    - Endpoint examples: a valid LLM response gives `fallback=false` and the full single-response shape, the LLM request carries the table ids and the `json_schema` response format, coordinates with `/api/plan` out of range give 422 naming the field and no AQI_Service call.
    - _Requirements: 2.3, 6.12, 13.1_

- [x] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. HTML frontend for the plan
  - [x] 7.1 Build the form, geolocation, localStorage, and API calls
    - Replace the placeholder `public/index.html` with one file containing inline `<style>` and `<script>`, no framework and no external resources. Add the sticky disclaimer banner, the city input, the "Use my location" button with a 10 s guard timer and loading state, the Household_Profile form, Generate and Clear saved profile buttons.
    - Implement the `el(tag, text, cls)` factory as the only element creator, `isValidProfile()`, try/catch localStorage save, load, prefill, and clear, with invalid saved data removed. Fill the city with `My location` when coordinates are used and the city is empty.
    - Implement `fetch` calls to `/api/plan`, with a plain-language message per error code, a 422 field list, and the 429 `Retry-After` seconds.
    - No `innerHTML`, `outerHTML`, or `insertAdjacentHTML` anywhere.
    - _Requirements: 2.1, 2.4, 2.6, 4.1, 4.4, 4.5, 4.6, 4.7, 4.9, 11.3, 11.4, 12.2, 15.3, 15.4_

  - [x] 7.2 Render the AQI banner, notices, plan, impact table, and disclaimer
    - Render the AQI card (value, band, GRAP stage with the label "indicative, not an official declaration"), the estimated-data notice and the rule-based fallback notice above the plan, the Exposure_Score, the four routine slots, indoor hacks, swaps, the vulnerable-members note, each item's why-it-matters text, and the Impact_Table with action, percentage, CO2 kg/day, approximate marking, basis, and source note.
    - Show the "no further actions apply" message when the table is empty. Keep all dynamic text on `textContent` or text nodes.
    - Demo: open the page through `uvicorn`, generate a plan, and see every section.
    - _Requirements: 1.7, 2.5, 3.3, 5.10, 5.12, 6.13, 7.7, 11.3, 15.3, 15.4_

  - [x] 7.3 Write static checks for the page
    - `tests/test_static_frontend.py`: no `innerHTML`, `outerHTML`, or `insertAdjacentHTML`, no external `<script src>` or stylesheet link, the indicative GRAP label, the disclaimer text, the estimated and fallback notice strings, and `localStorage` access inside `try`.
    - _Requirements: 1.7, 3.3, 7.7, 11.3, 11.4, 12.2, 15.3_

- [x] 8. Chat follow-up
  - [x] 8.1 Add the chat models
    - In `airwise/models.py`, add `ChatTurn`, `ChatRequest` (message trimmed non-empty and at most 500, history at most 10, plan, reading, profile), `ChatReply`, and `LLMChat`.
    - _Requirements: 8.1, 8.6, 8.7, 9.3, 9.4, 9.5_

  - [x] 8.2 Implement the Chat_Service and scope guard
    - Create `airwise/services/chat.py` with `out_of_scope` (case-insensitive diagnosis, treatment, medication, and official-GRAP-declaration triggers), `answer`, `CHAT_JSON_SCHEMA`, the fixed off-topic reply (at most 2 sentences), `NOT_MEDICAL_ADVICE_NOTE`, and `CHAT_FAILURE_MESSAGE`.
    - Order: scope guard, missing key, deadline check, one LLM call with no retry, validate `{reply, on_topic, discusses_health}`, apply the off-topic and medical note rules. Return `failed=True` on any failure. No streaming and no stored state.
    - _Requirements: 8.2, 8.3, 8.4, 8.5, 8.10, 8.11, 12.7, 15.5_

  - [x] 8.3 Write property tests for chat replies and scope
    - **Property 17: Health replies carry the not-medical-advice note**
    - **Validates: Requirements 8.4, 8.5**
    - **Property 18: Out-of-scope chat requests are declined without the LLM**
    - **Validates: Requirements 15.5**

  - [x] 8.4 Add `POST /api/chat`
    - In `airwise/main.py`, add the route returning `ChatReply` with HTTP 200 for both success and failure replies (`failed=true`). Reuse the LLM client and deadline dependencies.
    - _Requirements: 8.1, 8.2, 8.10, 8.11, 12.7_

  - [x] 8.5 Write property test and endpoint tests for chat
    - **Property 8: Chat message and history bounds**
    - **Validates: Requirements 8.6, 8.7**
    - Extend the Property 7 coverage to `/api/chat` in `tests/test_chat_validation.py` (oversized strings, more than 50 list items, malformed plan, reading, or profile).
    - Endpoint examples: statelessness (same request gives the same LLM payload), failure message on missing key, error, and timeout, fixed off-topic reply, scope decline with no LLM call.
    - **Validates: Requirements 4.3, 9.1, 9.3, 9.4, 9.5**
    - _Requirements: 8.2, 8.10, 8.11, 13.1_

  - [x] 8.6 Add the chat panel to the page
    - In `public/index.html`, add the chat panel: 3 to 5 starter question buttons, history list, input, and Send. Keep `plan`, `reading`, `profile`, and `history` in JS variables and send the last 10 history entries with each request. Hide starters after the first send. On failure append the failure message as an assistant bubble and keep earlier bubbles. Use `el()` and `textContent` only.
    - Demo: generate a plan, click a starter question, and see the reply or failure message inline.
    - _Requirements: 8.1, 8.8, 8.9, 8.10, 11.3, 11.4_

  - [x] 8.7 Write static checks for the chat panel
    - `tests/test_static_chat.py`: 3 to 5 starter questions, no forbidden DOM assignments, history trimmed to 10 in the script.
    - _Requirements: 8.8, 11.4_

- [x] 9. Hardening, README, and deployment steps
  - [x] 9.1 Add the body-size limit middleware
    - Create `airwise/middleware.py` with a pure ASGI `BodySizeLimitMiddleware`: reject with 413 `payload_too_large` when `Content-Length` exceeds 65,536, and count streamed bytes for chunked bodies, without invoking the route. Register it in `create_app()`.
    - _Requirements: 9.2_

  - [x] 9.2 Write property test for the body size limit
    - **Property 19: Body size limit**
    - **Validates: Requirements 9.2**

  - [x] 9.3 Add the rate limiter and client IP extraction
    - Create `airwise/ratelimit.py` with `FixedWindowLimiter` (injectable clock, opportunistic cleanup above 10,000 keys, rejections do not change the count) and `client_ip(request)` in `airwise/middleware.py`. Add `Retry-After` support to the 429 `AppError`.
    - Wire two limiters (plan 10 and chat 30 per 60 s) as FastAPI dependencies on `/api/plan` and `/api/chat`, created in `create_app()` so state is per app.
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

  - [x] 9.4 Write property tests for the limiter and client IP
    - **Property 20: Fixed-window rate limiting**
    - **Validates: Requirements 10.1, 10.2, 10.3**
    - **Property 21: Client IP extraction**
    - **Validates: Requirements 10.4, 10.5**
    - Endpoint examples: the 11th plan request returns 429 with `Retry-After` and the fake LLM count stays at 10 or below, plan and chat quotas are independent.

  - [x] 9.5 Add the catch-all error handler
    - In `airwise/main.py`, add the `Exception` handler that logs only the exception class name and returns 500 `server_error` with a generic message. Ensure no handler, log line, or response includes environment values or SDK exception text.
    - _Requirements: 11.2, 11.6, 11.7_

  - [x] 9.6 Write tests for error handling and secret hygiene
    - A forced exception returns the generic 500 body with no traceback or path. A fake key set through `monkeypatch` never appears in any response body, header, or captured log, including after an LLM failure.
    - _Requirements: 11.2, 11.6, 11.7, 13.1_

  - [x] 9.7 Write the README
    - Create `README.md` with sections: feature set, local setup (numbered steps with the supported Python version found in task 1.1, install command, and the uvicorn start command), environment variables (name, required or optional, purpose, default for `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, and `LLM_MODEL`), running pytest (exact command from the repository root), Vercel deployment (numbered steps: import the repository, set `ANTHROPIC_API_KEY`, optionally set `LLM_MODEL`, deploy, confirm via `/api/health` and the page, and state the default model `claude-haiku-5-5`), the manual browser checklist from the design, known limits, and a disclaimer section (figures approximate, GRAP stage indicative, no medical advice).
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 14.7_

- [x] 10. Final checkpoint - Ensure all tests pass
  - Run the full suite with no network and no API key and confirm it finishes within 60 seconds. Ensure all tests pass, ask the user if questions arise.

## Notes

- All tasks, including test tasks, are required.
- Each task references specific requirements for traceability. Property tests carry the design's property numbers.
- Existing scaffold files are reviewed and aligned, not overwritten blindly.
- Unit tests validate specific examples and edge cases. Property tests validate universal correctness properties.
- The browser checks (geolocation, localStorage, visible disclaimer) are manual and are listed in the README.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["1.3", "2.1"] },
    { "id": 3, "tasks": ["2.2"] },
    { "id": 4, "tasks": ["2.3", "2.4", "2.5"] },
    { "id": 5, "tasks": ["2.6", "2.7"] },
    { "id": 6, "tasks": ["2.8", "4.1"] },
    { "id": 7, "tasks": ["4.2", "4.3"] },
    { "id": 8, "tasks": ["4.4", "4.5", "4.6", "5.1"] },
    { "id": 9, "tasks": ["5.2", "5.4", "8.1"] },
    { "id": 10, "tasks": ["5.3", "5.5", "5.6", "8.2"] },
    { "id": 11, "tasks": ["5.7", "5.8", "5.9", "5.10", "8.3"] },
    { "id": 12, "tasks": ["5.11", "7.1", "8.4"] },
    { "id": 13, "tasks": ["7.2", "8.5", "9.1"] },
    { "id": 14, "tasks": ["7.3", "8.6", "9.2", "9.3"] },
    { "id": 15, "tasks": ["8.7", "9.4", "9.5"] },
    { "id": 16, "tasks": ["9.6", "9.7"] }
  ]
}
```
