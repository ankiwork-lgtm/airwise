# AirWise

AirWise is a GenAI web assistant that helps families in India handle severe winter smog. It reads the current air quality for your location, asks a short household questionnaire, and builds a personalized plan of low-emission routines, indoor air hacks, and sustainable swaps. A follow-up chat answers questions about the plan.

The backend is a Python FastAPI app deployed as a single Vercel serverless function. The frontend is one HTML page with vanilla JavaScript and no build step. There is no database and there are no user accounts.

## Feature set

- Live AQI for a city name or for browser coordinates, using the Open-Meteo Geocoding and Air Quality APIs (no API key needed). The AQI is computed from PM2.5 and PM10 with CPCB breakpoints and shown with its CPCB band and an indicative GRAP stage.
- Estimated typical winter reading when the Air Quality API is unavailable, clearly flagged as estimated.
- Household profile form (kids, elderly, respiratory condition, commute, cooking fuel, heating, purifier, window ventilation), saved in the browser's localStorage.
- Deterministic impact table: estimated exposure reduction and CO2 kg/day saved per action, plus an overall exposure score. The language model only explains these figures and never invents numbers.
- Personalized plan (daily routine, indoor hacks, sustainable swaps, vulnerable-members note) with a "why it matters" line for each item.
- Rule-based fallback plan when the OpenAI key is missing or the LLM call fails, times out, or returns invalid output.
- Stateless follow-up chat about the plan, with suggested starter questions.
- Input validation, a 64 KB request size limit, and per-IP rate limiting (10 plan requests and 30 chat requests per 60 seconds).

## Local setup

1. Install Python 3.10 or newer (`requires-python = ">=3.10"` in `pyproject.toml`). The project's `.venv` uses Python 3.15.2.
2. Create and activate a virtual environment.
   - Windows PowerShell: `python -m venv .venv` then `.venv\Scripts\Activate.ps1`
   - macOS/Linux: `python -m venv .venv` then `source .venv/bin/activate`
3. Install the package with its dev dependencies:
   ```
   pip install -e ".[dev]"
   ```
4. Copy `.env.example` to `.env` and set `OPENAI_API_KEY`. Export the variables into your shell, because the app reads process environment variables only. Without a key, AirWise still runs and returns rule-based fallback plans.
5. Start the server:
   ```
   uvicorn airwise.main:create_app --factory
   ```
6. Open http://127.0.0.1:8000 in a browser.

## Environment variables

These are all the variables defined in `.env.example`.

| Name | Required or optional | Purpose | Default |
| --- | --- | --- | --- |
| `OPENAI_API_KEY` | Required for AI-personalized plans and chat. Optional to run the app: without it, plans use the rule-based fallback and chat reports that answers are unavailable. | API key for the OpenAI chat completions API. Read from the process environment only. | None |
| `OPENAI_MODEL` | Optional | OpenAI model used for plans and chat. | `gpt-4o-mini` (also used when the variable is empty) |

Never commit a real key. `.env.example` holds a placeholder only.

## Running pytest

From the repository root, with the virtual environment active:

```
pytest
```

The tests mock the Open-Meteo and OpenAI APIs, make no network calls, and need no OpenAI key.

## Deploying to Vercel

1. Push the repository to GitHub, GitLab, or Bitbucket and import it as a new project in Vercel. No build command is needed.
2. In Project Settings, then Environment Variables, add `OPENAI_API_KEY` with your OpenAI key.
3. Optionally add `OPENAI_MODEL`. If you do not set it, AirWise uses the default model `gpt-4o-mini`.
4. Deploy. `vercel.json` routes `/api/*` to the `api/index.py` function (`maxDuration` 30 seconds) and serves the page from `public/`.
5. Confirm the deployment: open `/api/health` and check that it returns a healthy response, then open the root page and generate a plan for a city.

## Manual browser checklist

These behaviors depend on the browser and are not covered by automated tests. Check them before a release.

- Geolocation: grant permission and confirm the AQI loads; deny permission and confirm the "enter a city name" message appears and the city input stays enabled; let it time out (10 seconds) and confirm the same.
- localStorage: generate a plan and reload to confirm the form is prefilled; use clear-saved-profile and confirm the form empties; corrupt the saved entry (edit it in dev tools) and confirm the page shows an empty form and removes the entry; disable localStorage and confirm the plan still displays without a blocking error.
- Loading indicators: confirm one shows during the location lookup, plan generation, and chat, and that the related controls are disabled meanwhile.
- Disclaimer: confirm it is visible on the page, and that the "indicative" label appears next to any GRAP stage and the estimated-data and fallback notices show without scrolling or interaction.

## Known limits

- Rate limiting is in memory and per warm serverless instance. A client served by several instances can exceed the stated limits.
- The AQI uses instantaneous Open-Meteo PM2.5 and PM10 values, not CPCB 24-hour averages, so it only approximates the official AQI.
- Chat replies are grounded in the supplied plan and impact table through the prompt. This cannot be fully verified by code.
- Worst-case sequential latency (8 s + 8 s + 20 s) exceeds `maxDuration` of 30 s. A 28 s request deadline shortens the LLM timeout in that case.
- English only, and India only (CPCB bands, indicative GRAP stages, Indian cities).

## Disclaimer

- All impact figures (exposure reduction and CO2 savings) are approximate estimates from fixed rules.
- The GRAP stage is indicative, derived from the computed AQI. It is not an official declaration.
- AirWise does not provide medical advice. Consult a qualified doctor for health concerns.
