# AirWise improvement plan

This plan addresses the gaps found in the evaluation against the review criteria: code quality, security, efficiency, testing, accessibility, and problem statement alignment.

Baseline: 116 tests pass (`pytest`, about 30 s, no network).

Notes that shape the plan:

- Several tests patch `llm._TRANSPORT` ([`test_llm_client.py`](tests/test_llm_client.py), [`test_error_hygiene.py`](tests/test_error_hygiene.py), [`test_plan_validation.py`](tests/test_plan_validation.py)). Reusing one LLM HTTP client must keep that hook working.
- [`test_static_frontend.py`](tests/test_static_frontend.py) reads only `index.html`. If the script moves out for a strict CSP, those tests must also read the new files.
- Locally, FastAPI serves only `/`. Vercel serves `public/` statically. Any new static file needs a local route or mount, or the dev server breaks.

## Phase 1: Safe cleanup (no behaviour change)

| # | Change | Files |
|---|---|---|
| 1.1 | Move `_figures` into one shared place (for example `ImpactFigures.from_row` in `models.py`) and delete the duplicates. | `airwise/services/plan.py`, `airwise/services/fallback.py`, `airwise/models.py` |
| 1.2 | Make `_FACTOR_ITEM`, `_context_factors` and `_vulnerable_note` public (drop the underscore) and update the imports. | `airwise/services/fallback.py`, `airwise/services/plan.py` |
| 1.3 | Replace `except (ValidationError, Exception)` with `except Exception:` plus a comment saying why the catch is broad. | `airwise/services/plan.py`, `airwise/services/chat.py` |
| 1.4 | Remove the dead re-validation in `impact._validate`. Keep the `None` checks only if a test needs them. | `airwise/services/impact.py` |
| 1.5 | Change the `max_length=2000` on `impact_id` and `ImpactRow.id` to a sensible bound (for example 64). | `airwise/models.py` |
| 1.6 | Fix the stale "Task 7.2" comment and the `@ai-sdk/anthropic` mention in `.env.example`. | `public/index.html`, `.env.example` |
| 1.7 | Confirm `claude-haiku-5-5` is a valid model ID with the gateway and fix the default if it is not. Needs owner input. | `airwise/config.py`, `README.md` |

Verify: `pytest` stays at 116 passing.

## Phase 2: Tooling and CI

| # | Change |
|---|---|
| 2.1 | Add `ruff`, `mypy`, `pytest-cov` and `pip-audit` to the dev extras in `pyproject.toml`. Add `[tool.ruff]`, `[tool.mypy]` and coverage config. Pin to current stable versions and check each is maintained. |
| 2.2 | Generate a lock file (`requirements.lock` or `uv.lock`) and pin runtime dependencies to a tested range. |
| 2.3 | Add `.github/workflows/ci.yml` running ruff, mypy, `pytest --cov --cov-fail-under=N` and `pip-audit`. Use least-privilege `permissions: contents: read`. |
| 2.4 | Run the tools and fix what they report, in small commits. |

Verify: CI is green on a clean checkout. Record the baseline coverage number.

## Phase 3: Security

| # | Change | Files |
|---|---|---|
| 3.1 | Add a rate limiter for `/api/aqi` (for example 30 per 60 s). Reuse `FixedWindowLimiter` and add an `AQI_LIMIT` constant. | `airwise/main.py`, `airwise/config.py` |
| 3.2 | Document the `X-Forwarded-For` trust assumption in the README (safe on Vercel only) and add a test for a malformed header. | `README.md`, `tests/test_ratelimit.py` |
| 3.3 | In `chat.py`, log the exception class and status code only, not the message. | `airwise/services/chat.py` |
| 3.4 | Add security headers in `vercel.json`: `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`, `Permissions-Policy: geolocation=(self)`, and a strict `Content-Security-Policy`. | `vercel.json` |
| 3.5 | Add the same headers to local FastAPI responses through a small ASGI middleware, so tests can check them. | `airwise/middleware.py`, `airwise/main.py` |
| 3.6 | To allow a strict CSP (`script-src 'self'; style-src 'self'`), move the CSS and JS out of `index.html` into `public/app.css` and `public/app.js`. | `public/` |

Dependencies for 3.6:

- Add a local route or `StaticFiles` mount for `/app.js` and `/app.css`.
- Update the static tests to read all three files.
- Confirm `includeFiles: public/**` in `vercel.json` still covers them.

Verify: new tests assert the headers are present and `/api/aqi` returns 429 when over the limit. `pip-audit` reports no known vulnerabilities.

Optional, larger change: stop trusting client-supplied `plan`, `reading` and `profile` in `/api/chat`. This needs signing or server-side recomputation. Suggested default: document it as a known limit.

## Phase 4: Efficiency

| # | Change | Files |
|---|---|---|
| 4.1 | Reuse one `httpx.AsyncClient` in `AnthropicClient`, created lazily, with the `_TRANSPORT` hook still honoured. The per-call timeout moves to the request. | `airwise/services/llm.py` |
| 4.2 | Add a FastAPI lifespan handler that closes the shared clients on shutdown. | `airwise/main.py` |
| 4.3 | Read `index.html` once and cache it at import (the `/` route is only used locally). | `airwise/main.py` |
| 4.4 | Add a small TTL cache (for example 5 minutes) for geocode and PM lookups, keyed by city or rounded coordinates, with a size cap. | `airwise/services/aqi.py` |
| 4.5 | Lower `MAX_OUTPUT_TOKENS` or tighten the plan prompt if measured plans are well under 2048 tokens. | `airwise/services/llm.py` |

Verify: existing LLM tests pass with the monkeypatched transport. Add a test that two consecutive calls reuse one client, and one that a repeated city lookup hits upstream once.

Risk: a cache between tests can leak state. Reset it in `tests/conftest.py`.

## Phase 5: Accessibility (frontend)

| # | Change |
|---|---|
| 5.1 | Add `@media (prefers-reduced-motion: reduce)` to stop the spinner animation. |
| 5.2 | Use `role="alert"` for error status regions. Set `aria-invalid="true"` and `aria-describedby` on fields the API reports as invalid, and focus the first invalid field. |
| 5.3 | After rendering results, move focus to the results heading (`tabindex="-1"`). |
| 5.4 | Add a `<caption>` and `scope="col"` to the impact table. |
| 5.5 | Add visually hidden "You:" and "AirWise:" prefixes to chat bubbles. |
| 5.6 | Add `:focus-visible` styles. Recheck colour contrast (button text, `.why`, `.muted`) against WCAG AA 4.5:1 and adjust colours. |
| 5.7 | Add a skip link, and `<header>` and `<footer>` landmarks. |
| 5.8 | Make the sticky disclaimer non-sticky on small screens or at high zoom. |
| 5.9 | Add keyboard and screen-reader steps to the README manual checklist. |

Verify: extend the static tests to check for the new attributes and the reduced-motion rule. Run an axe or Lighthouse pass in Phase 6 and fix anything it finds.

## Phase 6: Frontend tests

| # | Change |
|---|---|
| 6.1 | Add Playwright (Python) to the dev extras, with a fixture that starts the app on `127.0.0.1` and mocks `/api/*` with `page.route`. |
| 6.2 | Cover: form validation errors, successful plan render, geolocation denied and timeout, `localStorage` prefill and clear, chat send and failure, and the loading and disabled states. |
| 6.3 | Add an `axe-core` check for the main page states, and a keyboard-only path test. |
| 6.4 | Mark the browser tests with a pytest marker so the fast suite runs without browsers. Run them in a separate CI job. |

Verify: the browser suite passes locally and in CI. The README manual checklist shrinks to what is genuinely manual.

Risk: Playwright needs a browser download. Check its maintenance status and latest stable version before adding it, per the project security rules.

## Order and sizing

1. Phase 1 (small), then Phase 2 (small to medium). This sets a safe baseline.
2. Phase 3.1 to 3.3 (small), then Phase 4 (medium).
3. Phase 3.4 to 3.6 together with Phase 5 (medium). These all touch the frontend files, so doing them together avoids rework.
4. Phase 6 (medium to large), which also verifies Phases 3.6 and 5.

Each phase is a separate commit or PR, and the full suite must stay green at the end of each one.

## Open questions (all answered)

- Is `claude-haiku-5-5` the correct model ID for the gateway? Yes. It worked against the configured gateway in the TF.2 smoke test.
- Are Playwright browser tests (Phase 6) wanted, or are they too heavy for this submission? Wanted. They sit behind a skippable `browser` marker and run in their own CI job.
- Should the "don't trust client plan" change in `/api/chat` be implemented, or documented as a limitation? Documented as a known limit (README "Known limits").

## Progress

- [x] Phase 1: Safe cleanup
- [x] Phase 2: Tooling and CI
- [x] Phase 3: Security
- [x] Phase 4: Efficiency (T4.5, the LLM output size review, was skipped: it needs a real key and was not measured)
- [x] Phase 5: Accessibility
- [x] Phase 6: Frontend tests
