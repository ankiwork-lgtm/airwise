# AirWise improvement tasks

Task breakdown of [`PLAN.md`](PLAN.md). Each task is small enough for one commit. Run `pytest` after every task; the suite must stay green (baseline: 116 passing).

Legend: `[ ]` to do, `[x]` done. "Needs input" means the task is blocked on an owner decision.

## Phase 1: Safe cleanup (no behaviour change)

- [x] **T1.1 Share the `_figures` helper**
  - Add one shared builder (implemented as `ImpactRow.figures()`) in `airwise/models.py`.
  - Delete the duplicate `_figures` in `airwise/services/plan.py` and `airwise/services/fallback.py` and use the shared one.
  - Done when: no duplicate `_figures` remains and tests pass.
- [x] **T1.2 Make shared fallback helpers public**
  - In `airwise/services/fallback.py`, rename `_FACTOR_ITEM`, `_context_factors`, `_vulnerable_note` to public names.
  - Update imports in `airwise/services/plan.py` and any tests.
  - Done when: no module imports an underscore-private name from another module.
- [x] **T1.3 Fix broad `except` clauses**
  - Replace `except (ValidationError, Exception)` with `except Exception:` plus a one-line comment in `airwise/services/plan.py` and `airwise/services/chat.py`.
  - Remove the unused `ValidationError` imports.
- [x] **T1.4 Remove dead validation in `impact._validate`** (closed, won't do)
  - Not dead code. `compute_impact` is a public entry point, and `tests/test_impact_unit.py` passes objects built with `model_construct`, which skips Pydantic validation.
  - Only the `model_validate(model_dump())` calls in `airwise/services/impact.py` reject those with `InvalidInput`. Removing them would break 4 tests and drop a real guard, so the code stays as is.
- [x] **T1.5 Tighten ID field lengths**
  - Change `max_length=2000` on `ImpactRow.id` and `impact_id` fields in `airwise/models.py` to 64.
  - Check the `LLMItem` and `PlanItem` fields and `tests/strategies.py` still generate valid data.
  - Scope narrowed: only the server-owned fields `ImpactRow.id` and `PlanItem.impact_id` are now 64. `LLMItem.impact_id` stays at 2000 on purpose: an over-long LLM id would otherwise fail validation of the whole `LLMPlan` and force the rule-based fallback, whereas today `airwise/services/plan.py` just turns an unknown id into `None`.
- [x] **T1.6 Remove stale comments and wrong config text**
  - Delete the "Task 7.2" comment in `public/index.html`.
  - Remove the `@ai-sdk/anthropic` mention from `.env.example`.
- [x] **T1.7 Confirm the default model ID**
  - Owner confirmed `claude-haiku-5-5` is valid for the gateway. No change needed to `airwise/config.py` or the README env table.

## Phase 2: Tooling and CI

- [x] **T2.1 Add dev tooling config**
  - Add `ruff`, `mypy`, `pytest-cov`, `pip-audit` to the dev extras in `pyproject.toml`.
  - Check each is actively maintained and use the latest stable version.
  - Add `[tool.ruff]`, `[tool.mypy]` and coverage settings.
- [x] **T2.2 Add a dependency lock file**
  - Generate a lock file (`requirements.lock` or `uv.lock`) from `pyproject.toml`.
  - Document how to regenerate it in the README.
- [x] **T2.3 Fix ruff findings**
  - Run `ruff check` and `ruff format --check`, and fix what is reported.
- [x] **T2.4 Fix mypy findings**
  - Run `mypy airwise` and fix what is reported (including the `# type: ignore` spots where a real fix is possible).
  - Two narrow `# type: ignore[arg-type]` remain in `airwise/main.py` (Starlette's `add_exception_handler` is typed for `Exception` handlers, so narrower handlers for `AppError` / `RequestValidationError` are flagged); each has a reason comment.
- [x] **T2.5 Measure coverage**
  - Run `pytest --cov=airwise` and record the baseline in the README.
  - Pick a `--cov-fail-under` threshold just below the baseline.
- [x] **T2.6 Add the CI workflow**
  - Create `.github/workflows/ci.yml` running ruff, mypy, pytest with coverage, and `pip-audit`.
  - Set `permissions: contents: read` and pin action versions.
  - Done when: the workflow passes on a clean checkout.
  - Note: CI could not be run in this environment. Every step was run locally on Python 3.15 and passed, but the workflow must be confirmed green on the first push (including the Python 3.11 job).

## Phase 3: Security

- [x] **T3.1 Rate-limit `/api/aqi`**
  - Add `AQI_LIMIT` to `airwise/config.py` (for example 30 per `WINDOW_S`).
  - Add a limiter and check in `airwise/main.py` for `/api/aqi`.
  - Add tests: allowed under the limit, 429 with `Retry-After` over it.
- [x] **T3.2 Document and test the proxy-header trust**
  - Add a README note: `X-Forwarded-For` is trusted, which is safe on Vercel only.
  - Add a test in `tests/test_ratelimit.py` for a malformed `X-Forwarded-For` header.
- [x] **T3.3 Stop logging upstream error text**
  - In `airwise/services/chat.py`, log the exception class (and status code if present), not the message.
  - Add a test that the log record contains no response body.
- [x] **T3.4 Add local security-headers middleware**
  - Add a small ASGI middleware in `airwise/middleware.py` setting `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options` and `Permissions-Policy`.
  - Register it in `create_app`.
  - Add tests that the headers appear on `/`, `/api/health`, and error responses.
- [x] **T3.5 Add security headers for Vercel**
  - Add a `headers` block in `vercel.json` with the same headers.
  - Add a test that parses `vercel.json` and checks the headers are present.
  - Note: confirm the headers on a real Vercel deployment after the first deploy, for example `curl -I https://<deployment>/` and `curl -I https://<deployment>/api/health`.
- [x] **T3.6 Move CSS and JS to separate files**
  - Create `public/app.css` and `public/app.js` from the inline blocks in `public/index.html`, and link them.
  - Serve both locally (route or `StaticFiles` mount in `airwise/main.py`).
  - Update `tests/test_static_frontend.py` to read all three files.
  - Confirm `includeFiles: public/**` in `vercel.json` covers them.
  - Done when: the page works unchanged locally and the static tests pass.
- [x] **T3.7 Add a strict CSP**
  - Add `Content-Security-Policy` (`default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'`) to the local middleware and `vercel.json`.
  - Confirm no inline script or style remains. Add a test that asserts this.
  - Depends on: T3.4, T3.5, T3.6.
  - Note: confirm the CSP on a real deployment with a browser console check (no violations). No `report-uri` / `report-to` is configured.
- [x] **T3.8 Decide on trusting client data in `/api/chat`**
  - Decision: document it as a known limit (owner's choice). Added a bullet to the README "Known limits".
  - Not done, by design: server-side signing or recomputation of the plan. It would change the request format and the frontend. Revisit only if chat is ever given stored or shared data.

## Phase 4: Efficiency

- [x] **T4.1 Reuse one LLM HTTP client**
  - In `airwise/services/llm.py`, create the `httpx.AsyncClient` lazily and reuse it.
  - Pass the per-call timeout on the request.
  - Keep the `_TRANSPORT` hook working so existing tests still pass.
  - Add a test that two calls reuse one client.
- [x] **T4.2 Close shared clients on shutdown**
  - Add a FastAPI lifespan handler in `airwise/main.py` that closes the Open-Meteo and LLM clients.
- [x] **T4.3 Cache `index.html`**
  - Read it once instead of on every `/` request in `airwise/main.py`.
- [x] **T4.4 Add a TTL cache for geocode and PM lookups**
  - Add a small bounded cache (about 5 minutes) in `airwise/services/aqi.py`.
  - Key by city (normalised) or rounded coordinates.
  - Reset the cache in `tests/conftest.py`.
  - Add a test that a repeated lookup calls upstream once and that entries expire.
- [x] **T4.5 Review LLM output size** (skipped: needs a real LLM API key; not measured)
  - Measure typical plan token use and adjust `MAX_OUTPUT_TOKENS` or the prompt if justified.
  - Needs a real key; skip if unavailable and note it.

## Phase 5: Accessibility

All changes are in `public/index.html`, or in `public/app.css` and `public/app.js` after T3.6.

- [x] **T5.1 Respect reduced motion**
  - Add `@media (prefers-reduced-motion: reduce)` to disable the spinner animation.
- [x] **T5.2 Accessible form errors**
  - Use `role="alert"` for error status regions.
  - Set `aria-invalid` and `aria-describedby` on fields the API or client validation flags.
  - Move focus to the first invalid field.
- [x] **T5.3 Move focus to results**
  - Give the results heading `tabindex="-1"` and focus it after a plan renders.
- [x] **T5.4 Accessible impact table**
  - Add a `<caption>` and `scope="col"` on header cells.
- [x] **T5.5 Label chat speakers**
  - Add visually hidden "You:" and "AirWise:" prefixes to chat bubbles.
- [x] **T5.6 Focus styles and contrast**
  - Add `:focus-visible` styles.
  - Check text and button contrast for WCAG AA (4.5:1) and adjust colours.
- [x] **T5.7 Landmarks and skip link**
  - Add a skip link, `<header>` and `<footer>`.
- [x] **T5.8 Sticky banner at small sizes**
  - Make the disclaimer non-sticky on small screens and at high zoom.
- [x] **T5.9 Extend static tests**
  - In `tests/test_static_frontend.py`, assert the new attributes, the reduced-motion rule, the caption and the skip link.
- [x] **T5.10 Update the README checklist**
  - Add keyboard-only and screen-reader steps to the manual browser checklist.
- [x] **T5.11 Keep failed chat replies out of the history**
  - In `sendChat` in `public/app.js`, do not push a `failed: true` reply into `history`, so it is not sent back to the LLM on later turns.
  - Add a static test.
- [x] **T5.12 Answer `/favicon.ico` with an empty 204**
  - Add a `GET /favicon.ico` route in `airwise/main.py` that returns `204 No Content` with the security headers and no body, so browsers and logs don't show a 404 on every page load.
  - No icon asset is added. Add a test (status, empty body, security headers).
- [x] **T5.13 Starter-question focus and invalid-field styling**
  - After a starter question is used, `sendChat` hides the starters row, so keyboard focus can be lost. Move focus to the chat input (or the new reply) so it is not lost.
  - Add a visible style for `[aria-invalid="true"]` fields in `public/app.css` (for example a border or outline in the error colour that meets 3:1 contrast), so sighted users see which field is flagged.
  - Add static tests.

## Phase 6: Frontend tests

- [x] **T6.1 Add the browser test harness**
  - Add Playwright (Python) to the dev extras after checking maintenance and the latest stable version.
  - Add a fixture that starts the app on `127.0.0.1` and mocks `/api/*` with `page.route`.
  - Add a pytest marker so browser tests can be skipped.
- [x] **T6.2 Test form flows**
  - Cover: validation errors, successful plan render, loading and disabled states.
- [x] **T6.3 Test geolocation and storage**
  - Cover: permission denied, timeout, `localStorage` prefill, clear, and corrupted saved data.
- [x] **T6.4 Test chat**
  - Cover: send, starter questions, failure bubble, and history reset after a new plan.
- [x] **T6.5 Add accessibility checks**
  - Add an `axe-core` scan for the main page states and a keyboard-only path test.
  - Fix any violations found.
- [ ] **T6.6 Run browser tests in CI**
  - Add a separate CI job that installs browsers and runs the marked tests.
- [ ] **T6.7 Trim the manual checklist**
  - Remove items in the README now covered by automated tests.

## Final checks

- [ ] **TF.1** `ruff`, `mypy`, `pytest --cov` and `pip-audit` all pass locally and in CI.
- [ ] **TF.2** Manual smoke test: run the app, generate a plan, use chat, test with and without an API key.
- [ ] **TF.3** Update the README (setup, security, accessibility, testing, known limits) to match the final state.
- [ ] **TF.4** Tick off the Progress list in `PLAN.md`.
