# AirWise

AirWise is a GenAI web assistant that helps families in India handle severe winter smog. It reads the current air quality for your location, asks a short household questionnaire, and builds a personalized plan of low-emission routines, indoor air hacks, and sustainable swaps. A follow-up chat answers questions about the plan.

The backend is a Python FastAPI app deployed as a single Vercel serverless function. The frontend is `public/index.html` with `public/app.css` and `public/app.js` (vanilla JavaScript, no build step). There is no database and there are no user accounts.

## Feature set

- Live AQI for a city name or for browser coordinates, using the Open-Meteo Geocoding and Air Quality APIs (no API key needed). The AQI is computed from PM2.5 and PM10 with CPCB breakpoints and shown with its CPCB band and an indicative GRAP stage.
- Estimated typical winter reading when the Air Quality API is unavailable, clearly flagged as estimated.
- Household profile form (kids, elderly, respiratory condition, commute, cooking fuel, heating, purifier, window ventilation), saved in the browser's localStorage.
- Deterministic impact table: estimated exposure reduction and CO2 kg/day saved per action, plus an overall exposure score. The language model only explains these figures and never invents numbers.
- Personalized plan (daily routine, indoor hacks, sustainable swaps, vulnerable-members note) with a "why it matters" line for each item.
- Rule-based fallback plan when the Anthropic key is missing or the LLM call fails, times out, or returns invalid output.
- Stateless follow-up chat about the plan, with suggested starter questions.
- Input validation, a 64 KB request size limit, and per-IP rate limiting (10 plan requests, 30 chat requests, and 30 AQI lookups per 60 seconds).

## Local setup

1. Install Python 3.10 or newer (`requires-python = ">=3.10"` in `pyproject.toml`). The project's `.venv` uses Python 3.15.2.
2. Create and activate a virtual environment.
   - Windows PowerShell: `python -m venv .venv` then `.venv\Scripts\Activate.ps1`
   - macOS/Linux: `python -m venv .venv` then `source .venv/bin/activate`
3. Install the package with its dev dependencies:
   ```
   pip install -e ".[dev]"
   ```
4. Copy `.env.example` to `.env` and set `ANTHROPIC_API_KEY` (and `ANTHROPIC_BASE_URL` if you use a gateway). The app loads `.env` at startup, and its values override variables already set in your shell. When there is no `.env` (for example on Vercel), it uses the process environment. Restart the server after editing `.env`. Without a key, AirWise still runs and returns rule-based fallback plans.
5. Start the server:
   ```
   uvicorn airwise.main:create_app --factory
   ```
6. Open http://127.0.0.1:8000 in a browser.

## Environment variables

These are all the variables defined in `.env.example`.

| Name | Required or optional | Purpose | Default |
| --- | --- | --- | --- |
| `ANTHROPIC_API_KEY` | Required for AI-personalized plans and chat. Optional to run the app: without it, plans use the rule-based fallback and chat reports that answers are unavailable. | API key for the Anthropic Messages API (or a compatible gateway). Read from `.env` when present, otherwise from the process environment. | None |
| `ANTHROPIC_BASE_URL` | Optional | Base URL of the Messages API, ending before `/messages` (for example `https://api.servicesessentials.ibm.com/v1`). | `https://api.anthropic.com/v1` |
| `LLM_MODEL` | Optional | Model name sent to the Messages API. | `claude-haiku-5-5` |

Never commit a real key. `.env.example` holds a placeholder only.

## Running pytest

From the repository root, with the virtual environment active:

```
pytest
```

The tests mock the Open-Meteo and Anthropic APIs, make no network calls, and need no Anthropic key.

### Coverage

```
pytest --cov=airwise --cov-report=term-missing
```

Baseline on 2026-11-19, with branch coverage: 95.27% total (two runs gave the same figure). The enforced minimum is 93% (`fail_under` in `pyproject.toml`); it applies only when coverage is measured, so plain `pytest` is unaffected.

### Browser tests

End-to-end tests use Playwright (Python) to verify the frontend in a real browser against a local server on `127.0.0.1` with mocked APIs.

- Install browser binaries (optional if Chrome or Edge is installed):
  ```
  python -m playwright install chromium
  ```
- Run only browser tests:
  ```
  pytest tests/browser
  ```
- Skip browser tests:
  ```
  pytest -m "not browser"
  ```
- Browser selection: tests use bundled Chromium if installed, otherwise auto-detect installed system browsers (`msedge`, `chrome`). Set `AIRWISE_BROWSER_CHANNEL` (e.g. `chrome` or `msedge`) to override. When no browser can be launched, tests are skipped cleanly rather than failing.
- Require a browser: set `AIRWISE_REQUIRE_BROWSER=1` to make a missing or broken browser fail the run instead of skipping it, and to fail the run if any browser test is skipped. CI sets it in the `browser` job, so a broken browser install cannot give a green run with no tests. Leave it unset locally.
- Failure artifacts: when a browser test fails, a full-page screenshot and the page HTML are saved in `test-results/` (git-ignored), named after the test id.
- Coverage gate: it applies only when `--cov` is passed, so `pytest tests/browser` is unaffected; CI adds `--no-cov` anyway, because a frontend-only run would not reach 93%.
- Coverage: browser tests do not affect backend coverage; the 93% coverage gate passes with or without `-m "not browser"`.
- Accessibility scan: automated WCAG scans use a vendored copy of axe-core under `tests/browser/vendor/axe.min.js` (integrity-pinned with update instructions in `tests/browser/vendor/AXE_VERSION.md`).

## Dependency lock files

- `requirements.lock` pins the runtime dependencies. `requirements-dev.lock` pins the runtime and dev dependencies.
- Both files are hash-pinned (`--generate-hashes`) and were generated with [uv](https://docs.astral.sh/uv/) 0.13.9 for Python 3.10, with `--universal` so one file serves all platforms.
- Install exactly the locked versions and verify their hashes:
  ```
  pip install --require-hashes -r requirements-dev.lock
  ```
- Regenerate after changing `pyproject.toml` (requires `uv`):
  ```
  uv pip compile pyproject.toml --generate-hashes --universal --python-version 3.10 -o requirements.lock
  uv pip compile pyproject.toml --extra dev --generate-hashes --universal --python-version 3.10 -o requirements-dev.lock
  ```
- Vercel does not read these files. It installs from `pyproject.toml`, so the lock files only make local and CI installs reproducible.

## Continuous integration

`.github/workflows/ci.yml` runs two parallel jobs on every push to `main` and every pull request:

- `checks` (Python 3.11 and 3.15): `ruff check`, `ruff format --check`, `mypy`, `pytest -m "not browser"` with coverage (enforcing `fail_under`), and `pip-audit` on `requirements-dev.lock`.
- `browser` (Python 3.11): installs Playwright's Chromium (`python -m playwright install --with-deps chromium`) and runs `pytest tests/browser -m browser --no-cov`. It sets `AIRWISE_REQUIRE_BROWSER=1`, so it fails, rather than skips, if the browser cannot launch or any test is skipped. On failure it uploads `test-results/` (screenshots and page HTML) as an artifact kept for 7 days.

Both jobs install the hash-pinned `requirements-dev.lock`, then the project with `pip install --no-deps -e .`; Playwright's version, and so the browser build, comes from that lock. No secrets are needed, because the tests mock all network calls and the browser tests mock `/api/*`.

The workflow has read-only `contents` permission, and every action (`actions/checkout`, `actions/setup-python`, `actions/upload-artifact`) is pinned to a full commit SHA with the version in a trailing comment. `tests/test_ci_workflow.py` checks these properties.

Status: the workflow passed `actionlint` 1.7.12 but has not run on GitHub yet, so the CI browser path (bundled Chromium on `ubuntu-latest`) is unverified. The browser job has no browser download cache; each run downloads Chromium.

## Deploying to Vercel

1. Push the repository to GitHub, GitLab, or Bitbucket and import it as a new project in Vercel. No build command is needed.
2. In Project Settings, then Environment Variables, add `ANTHROPIC_API_KEY` with your key, and `ANTHROPIC_BASE_URL` if you use a gateway.
3. Optionally add `LLM_MODEL`. If you do not set it, AirWise uses the default model `claude-haiku-5-5`.
4. Deploy. `vercel.json` routes `/api/*` to the `api/index.py` function (`maxDuration` 30 seconds) and serves the page from `public/`.
   `vercel.json` also sets the security headers for the static files in `public/`, which never pass through the FastAPI middleware.
   Keep these values in sync with `SECURITY_HEADERS` in `airwise/middleware.py`; `tests/test_vercel_config.py` fails if they differ.

5. Confirm the deployment: open `/api/health` and check that it returns a healthy response, then open the root page and generate a plan for a city.

### Content-Security-Policy

A strict `Content-Security-Policy` is set (same-origin only; no inline scripts or styles). Any new inline script or style, third-party script, font or CDN needs the policy updated in `airwise/middleware.py` and `vercel.json`; `tests/test_csp.py` enforces that they match and that the page still fits the policy.
Never add `'unsafe-inline'` or `'unsafe-eval'`; move the code or styles into `public/app.js` or `public/app.css` instead.
No `report-uri` or `report-to` is configured, so violations only show in the browser console.

## Manual browser checklist

### Automated coverage

Automated test suites cover 97 browser test cases (out of 393 total tests in the project) using Playwright Chromium and vendored axe-core, alongside static frontend tests:

- Smoke, asset types, security headers, and initial flow: `tests/browser/test_smoke.py` (5 tests)
- Form validation errors, field error clearing, plan and impact table render, loading/disabled states, and reduced-motion spinner disabling: `tests/browser/test_form_flows.py` (10 tests)
- Geolocation error callbacks, timeout, localStorage prefill, clear-saved-profile, corrupt JSON recovery (20 variations), and storage quota/access errors: `tests/browser/test_geolocation_storage.py` (40 tests)
- Chat interactions, history trimming to 10 turns, history reset on new plan, starter activation focus, blank input refusal, and error alerts: `tests/browser/test_chat.py` (24 tests)
- Automated WCAG scans with vendored axe-core across all UI states: `tests/browser/test_accessibility.py` (11 tests)
- End-to-end keyboard journey, skip link, impact table scrolling with arrow keys, and reflow viewports: `tests/browser/test_keyboard_path.py` (3 tests)
- Responsive layout, sticky vs static disclaimer banner, and scroll-padding adjustments: `tests/browser/test_layout.py` (4 tests)
- Static DOM structure, landmarks, heading outline, ARIA attributes, and contrast math: `tests/test_static_frontend.py` (59 tests)
- Static chat script constraints and forbidden DOM sinks: `tests/test_static_chat.py` (3 tests)
- Strict Content Security Policy directives and header parity: `tests/test_csp.py` (14 tests)

The checklist below is trimmed to what automated tests do not cover: human visual judgement, real assistive technology speech output, native browser permission dialogs, alternative browser engines, and real mobile devices. Check them before a release.

- Geolocation permission prompt: click "Use my location" on a real browser and device to confirm the native browser permission prompt appears and behaves as expected (automated tests drive the Geolocation API and context permissions, but cannot test native browser dialogs).
- Visual notice checks: confirm that the "indicative" label next to the GRAP stage, the estimated-data notice, and fallback notices are visually clear without clipping or unwanted scrolling.
- Alternative browser engines and mobile devices: verify basic plan generation and chat in Firefox (Gecko), Safari (WebKit / iOS), and Chrome for Android, including touchscreen interactions and virtual keyboard behavior.

### Accessibility checks

These steps target WCAG 2.1 AA criteria. Passing them does not show WCAG conformance. Allow 10 to 15 minutes. Use a desktop browser at 100% zoom unless a step says otherwise. Generate one plan (for example for Delhi, with every profile field set) before the steps that need results, then use "Clear saved profile" when a step needs an empty form.

#### Keyboard only

Put the mouse aside for this group.

- [ ] Tab through the interactive controls and confirm that every focus ring is visually clear, distinct, unbroken, and never obscured by surrounding elements or the banner across different monitors and rendering engines (the complete tab path, focus movement, and outline presence are verified by `tests/browser/test_keyboard_path.py`).

#### Screen reader

Use NVDA with Firefox or Chrome on Windows, VoiceOver with Safari on macOS or iOS, or TalkBack or Narrator where available. Note which combination you used.

- [ ] Open the landmarks list. Expect a "Disclaimer" complementary landmark (the sticky not-medical-advice banner), a banner, a main landmark, a contentinfo landmark (the footer), and a named region for each section: Location, Household profile, and, once a plan exists, "Your air quality plan" and "Ask a follow-up".
- [ ] Open the headings list. Expect one h1 ("AirWise"), then h2 section headings, with h3 headings below them and no skipped levels.
- [ ] Submit the incomplete form. Expect the error message and its list of fields to be announced once, and the focused field to be announced as invalid.
- [ ] Generate a plan. Expect "Your air quality plan" to be announced when focus moves to it. "Generating your plan..." may be announced first. Expect no success message repeated after the heading.
- [ ] Move into the impact table. Expect the region to be announced as "Impact table", then the caption ("Estimated exposure and CO2 reduction for each recommended action. Figures are approximate."), then the column headers (Action, Exposure reduction (approx.), CO2 saved (approx.), Basis, Source) as you move between cells.
- [ ] Send a chat question. Expect your bubble to be announced as "You: ..." and the reply as "AirWise: ...", each once.
- [ ] Make a chat request fail (stop the server or go offline, then send a question). Expect the failed bubble to be announced as "AirWise (error): ...". The same message also appears in the chat status area, which is an alert, so it may be read twice. Confirm whether this double announcement is annoying and record it if so.
- [ ] Read the footer. Expect "AirWise gives general information only and is not medical advice. Air quality data from Open-Meteo."

#### Zoom, reflow and motion

- [ ] Set browser zoom to 200%. Expect all content and controls to stay usable and the disclaimer banner to scroll away with the page instead of staying pinned.
- [ ] Set browser zoom to 400% in a 1280 px wide window (320 CSS px wide). Expect no horizontal scrolling except inside the impact table wrapper, no cut-off text or controls, and a banner that is not pinned.
- [ ] At 400%, Tab through the page. Expect each focused control to stay in view and not be covered by anything.
- [ ] Increase only the text size (browser text-only zoom or the OS text size setting). Expect text to grow with no overlap and nothing cut off.

#### Colour and contrast

- [ ] Turn on a Windows contrast theme (forced colours). Expect text, buttons, inputs, selects, table borders, and the focus ring to stay visible and readable, and secondary buttons ("Use my location", "Clear saved profile", starter questions) to still look like buttons.
- [ ] Expect error messages to be understandable without colour: they are text, listed by field name with thicker borders.
- [ ] Optional: run the Lighthouse accessibility audit on the page with a plan shown. Expect no accessibility failures (automated axe-core scans already run in `tests/browser/test_accessibility.py`).

#### Not yet verified in a real browser or with assistive technology

Automated browser tests (97 tests in `tests/browser/`) verify DOM rendering, keyboard focus progression, ARIA attributes, responsive layout, and axe-core rules in Chromium via Playwright. However:

- The GitHub Actions CI workflow (`.github/workflows/ci.yml`) defines the `browser` job, but it has not yet run on GitHub, so CI execution on Ubuntu runners remains unverified.
- Assistive technology speech output (screen reader live announcements, rotor navigation, and double-announcement evaluation) cannot be automated and requires human testing.
- Real browser zoom (200% and 400%), text-only scaling, and Windows forced colours require manual inspection.
- Other browser engines (Firefox, Safari) and physical mobile devices have not been tested.

## Known limits

- Rate limiting is in memory and per warm serverless instance. A client served by several instances can exceed the stated limits.
- Client IP for rate limiting is the first valid `X-Forwarded-For` entry, otherwise the socket peer. This is safe only behind a proxy that sets or overwrites the header, as Vercel does.
  If the app is run directly (for example `uvicorn` exposed on a network) or behind a proxy that appends to the header instead of overwriting it, a client can send its own `X-Forwarded-For` and pick its own rate-limit bucket, bypassing the per-IP limits.
  Mitigation: keep the app bound to `127.0.0.1` locally, or put it behind a trusted proxy.
- The AQI uses instantaneous Open-Meteo PM2.5 and PM10 values, not CPCB 24-hour averages, so it only approximates the official AQI.
- Chat replies are grounded in the supplied plan and impact table through the prompt. This cannot be fully verified by code.
- `/api/chat` is stateless, so the browser sends back the `plan`, `reading` and `profile` it received, and the server does not check them against anything it issued. The request schema limits their shape, field lengths and list sizes, but a caller can still put arbitrary text and altered figures into them.
  What this means: the chat model answers from whatever the caller supplied, so figures in a chat reply are only as trustworthy as that input. The reply goes back to the same caller, and the per-IP chat limit, the 64 KB body limit and the prompt rules (treat supplied strings as data, never invent numbers, stay on topic) bound the cost and the effect. There is no cross-user exposure, because nothing is stored or shared.
  Not done: signing the plan on the server, or recomputing it from the profile and reading. Either would change the request format and the frontend.
- Worst-case sequential latency (8 s + 8 s + 20 s) exceeds `maxDuration` of 30 s. A 28 s request deadline shortens the LLM timeout in that case.
- The app closes its shared HTTP clients on shutdown through a lifespan handler. On Vercel serverless the process may be frozen without a shutdown, which is harmless.
- Geocode and air-quality lookups are cached in memory for about 5 minutes (at most 256 entries each), per instance and not shared between instances. A reading can therefore be up to 5 minutes old.
- On Vercel, `/favicon.ico` is not routed to the FastAPI function (`vercel.json` rewrites only `/api/*`), so the empty 204 answer applies to local `uvicorn` runs; the browser's automatic favicon request may still get a 404 on Vercel, which is harmless and has not been checked on a deployment.
- English only, and India only (CPCB bands, indicative GRAP stages, Indian cities).

## Disclaimer

- All impact figures (exposure reduction and CO2 savings) are approximate estimates from fixed rules.
- The GRAP stage is indicative, derived from the computed AQI. It is not an official declaration.
- AirWise does not provide medical advice. Consult a qualified doctor for health concerns.
