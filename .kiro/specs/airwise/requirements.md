# Requirements Document

## Introduction

AirWise is a GenAI-powered web assistant that helps families and communities in India navigate severe winter smog and urban air pollution. The assistant reads the current air quality for the user's location, collects a short household profile, and produces a personalized plan of low-emission daily routines, indoor air quality hacks, and sustainable swaps. Each plan item carries a "why it matters" explanation. A deterministic impact table quantifies estimated exposure reduction and CO2 savings; the language model only explains these figures and never invents numbers. Users can then ask follow-up questions about the plan in a stateless chat.

The system is a Python FastAPI backend deployed as a Vercel serverless function, serving a single HTML page with vanilla JavaScript and no build step. There is no database and there are no user accounts. The MVP is English only and India-focused (CPCB AQI bands, indicative GRAP stages, local pollution context).

## Glossary

- **AirWise**: The complete system, comprising the Backend and the Web_Page.
- **Backend**: The Python FastAPI application deployed as a Vercel serverless function.
- **Web_Page**: The single HTML page with vanilla JavaScript and no build step that users interact with.
- **AQI_Service**: The Backend component that retrieves air quality data and computes the AQI.
- **Geocoding_API**: The Open-Meteo Geocoding API, used without an API key.
- **Air_Quality_API**: The Open-Meteo Air Quality API, used without an API key.
- **CPCB_Band**: One of the Central Pollution Control Board AQI categories: Good, Satisfactory, Moderate, Poor, Very Poor, Severe.
- **AQI**: The India AQI value computed from PM2.5 and PM10 concentrations using CPCB breakpoints; the higher of the two sub-indices.
- **GRAP_Stage**: The indicative Graded Response Action Plan stage derived from the AQI: Stage I for AQI 201-300, Stage II for 301-400, Stage III for 401-450, Stage IV for above 450. It is labeled "indicative" and is not an official declaration.
- **Air_Reading**: A record containing city or coordinates, PM2.5, PM10, AQI, CPCB_Band, GRAP_Stage, and a source flag (live or estimated).
- **Estimated_Reading**: A typical winter Air_Reading used when the Air_Quality_API is unavailable, flagged as estimated.
- **Household_Profile**: The user-supplied profile containing city, presence of kids, presence of elderly members, respiratory condition, commute mode, cooking fuel, heating type, purifier ownership, and window ventilation habit.
- **Commute_Mode**: One of car, two_wheeler, bus_metro, walk_cycle, work_from_home.
- **Cooking_Fuel**: One of lpg, png, induction, biomass.
- **Heating_Type**: One of none, electric, biomass_burning.
- **Plan**: The personalized output containing daily routine (morning, commute, midday, evening), indoor hacks, sustainable swaps, a vulnerable-members note, a why-it-matters explanation per item, the Impact_Table, and the overall exposure-reduction score.
- **Plan_Generator**: The Backend component that produces a Plan.
- **Impact_Table**: A deterministic table computed by the Backend in which each row holds an action, an estimated exposure-reduction percentage, an estimated CO2 kg/day saved, a basis, and a source note, all marked approximate.
- **Impact_Engine**: The Backend component that computes the Impact_Table and the overall exposure-reduction score using fixed rules.
- **Exposure_Score**: The overall estimated exposure-reduction percentage for a Plan, computed by the Impact_Engine.
- **LLM_Client**: The Backend component that calls the Anthropic Messages API at the URL named by ANTHROPIC_BASE_URL (default https://api.anthropic.com/v1) using the ANTHROPIC_API_KEY environment variable and the model named by LLM_MODEL (default claude-haiku-5-5), requesting structured JSON output.
- **Fallback_Plan**: A rule-based Plan built from the Impact_Table without the LLM_Client and flagged as fallback.
- **Chat_Service**: The Backend component that answers follow-up questions about a Plan.
- **Chat_Request**: A request containing the Plan, Air_Reading, Household_Profile, chat history, and the user message.
- **Rate_Limiter**: The Backend component that limits requests per client IP address.
- **LLM_Timeout**: The maximum time the Backend waits for one LLM_Client call, set to 20 seconds.

## Requirements

### Requirement 1: Retrieve live AQI for a city

**User Story:** As a family member, I want to see the current air quality for my city, so that I know how severe the pollution is today.

#### Acceptance Criteria

1. WHEN a user submits a city name of 1 to 100 characters after trimming leading and trailing whitespace, THE AQI_Service SHALL resolve the city to coordinates using the Geocoding_API restricted to India and use the first (top-ranked) match returned.
2. WHEN coordinates are resolved, THE AQI_Service SHALL retrieve the current PM2.5 and PM10 concentrations in ug/m3 from the Air_Quality_API within 8 seconds.
3. WHEN PM2.5 and PM10 concentrations are retrieved, THE AQI_Service SHALL compute the AQI as the higher of the PM2.5 sub-index and the PM10 sub-index using CPCB breakpoints, rounded to the nearest integer and capped at 500.
4. WHEN the AQI is computed, THE AQI_Service SHALL assign the CPCB_Band: Good for 0-50, Satisfactory for 51-100, Moderate for 101-200, Poor for 201-300, Very Poor for 301-400, and Severe for 401-500.
5. WHEN the AQI is computed and is above 200, THE AQI_Service SHALL assign the indicative GRAP_Stage: Stage I for 201-300, Stage II for 301-400, Stage III for 401-450, and Stage IV for 451-500.
6. WHILE the AQI is 200 or below, THE AQI_Service SHALL report the GRAP_Stage as none.
7. WHEN the Web_Page displays a GRAP_Stage, THE Web_Page SHALL show next to it a label stating that the stage is indicative and not an official declaration.
8. IF the Geocoding_API returns no match for the submitted city in India, THEN THE AQI_Service SHALL return an error indicating that the city was not found, SHALL NOT call the Air_Quality_API, and SHALL display no AQI, CPCB_Band, or GRAP_Stage for that submission.
9. IF the submitted city name is empty or whitespace-only after trimming, or longer than 100 characters, THEN THE AQI_Service SHALL reject the request with an error indicating that the city name is invalid, without calling the Geocoding_API.
10. IF the Geocoding_API does not respond within 8 seconds or returns a failure, THEN THE AQI_Service SHALL return an error indicating that the location lookup is unavailable and SHALL NOT display an AQI, CPCB_Band, or GRAP_Stage.
11. IF the Air_Quality_API fails, times out, or returns no usable PM2.5 and PM10 value after the coordinates are resolved, THEN THE AQI_Service SHALL behave as specified in Requirement 3.

### Requirement 2: Retrieve live AQI for browser coordinates

**User Story:** As a user who does not know the exact city name, I want to use my device location, so that I get the air quality where I am.

#### Acceptance Criteria

1. WHEN a user selects the use-my-location control, THE Web_Page SHALL request the browser geolocation and, within 1 second of the browser returning a position, send the latitude and longitude as decimal degrees to the Backend.
2. WHEN the Backend receives a latitude between -90 and 90 inclusive and a longitude between -180 and 180 inclusive, THE AQI_Service SHALL return an Air_Reading for those coordinates using the same computation as for a city.
3. IF the latitude is outside -90 to 90, the longitude is outside -180 to 180, or either value is missing or non-numeric, THEN THE Backend SHALL reject the request with a validation error identifying the invalid field, SHALL NOT call the AQI_Service, and THE Web_Page SHALL display the validation error to the user.
4. IF the user denies the geolocation permission, the browser does not support geolocation, or the browser returns no position within 10 seconds of the request, THEN THE Web_Page SHALL display a message inviting the user to enter a city name instead, SHALL NOT send a request to the Backend, and SHALL keep the city name input enabled.
5. IF the AQI_Service returns an Estimated_Reading for valid coordinates, THEN THE Web_Page SHALL display the estimated-data notice specified in Requirement 3 and SHALL keep the use-my-location control enabled for retry.
6. WHILE a geolocation request or coordinate lookup is in progress, THE Web_Page SHALL display a loading indicator and disable the use-my-location control.

### Requirement 3: AQI service resilience

**User Story:** As a user, I want the app to keep working when the air quality service is down, so that I can still receive guidance.

#### Acceptance Criteria

1. IF the Air_Quality_API request fails, does not respond within 8 seconds, or returns a response in which both PM2.5 and PM10 values are absent, THEN THE AQI_Service SHALL return an Estimated_Reading with the source flag set to estimated and SHALL NOT return an error to the caller.
2. WHEN the Air_Quality_API returns a response containing at least one of PM2.5 or PM10, THE AQI_Service SHALL return a reading with the source flag set to live.
3. WHEN an Estimated_Reading is returned, THE Web_Page SHALL display a notice, visible without scrolling or user interaction, stating that the reading is an estimated typical winter value and not live data.
4. WHEN an Estimated_Reading is used, THE Plan_Generator SHALL set the estimated flag to true in the Plan response and SHALL still generate a complete Plan.
5. THE AQI_Service SHALL apply a timeout of 8 seconds to each Open-Meteo request, and SHALL make no more than 1 attempt per request, with no retries.

### Requirement 4: Household profile form

**User Story:** As a parent, I want to describe my household once, so that the advice fits my family and lifestyle.

#### Acceptance Criteria

1. THE Web_Page SHALL present a Household_Profile form with fields for city (free text, 1 to 100 characters), kids present (yes/no), elderly present (yes/no), respiratory condition (yes/no), Commute_Mode (single selection), Cooking_Fuel (single selection), Heating_Type (single selection), purifier ownership (yes/no), and window ventilation habit (single selection).
2. THE Backend SHALL accept only the values defined for Commute_Mode (car, two_wheeler, bus_metro, walk_cycle, work_from_home), Cooking_Fuel (lpg, png, induction, biomass), and Heating_Type (none, electric, biomass_burning).
3. IF a Household_Profile contains a value outside the permitted values, a missing required field, or a city that is empty or longer than 100 characters, THEN THE Backend SHALL reject the request with a validation error identifying each offending field and SHALL NOT generate a Plan.
4. WHERE the browser supports localStorage, WHEN the user generates a Plan, THE Web_Page SHALL save the Household_Profile in localStorage, replacing any previously saved Household_Profile.
5. IF the browser does not support localStorage or a save to localStorage fails, THEN THE Web_Page SHALL still display the generated Plan and SHALL NOT display a blocking error.
6. WHERE the browser supports localStorage, WHEN the Web_Page loads and a saved Household_Profile exists in localStorage, THE Web_Page SHALL prefill every form field with the saved values.
7. WHERE the browser supports localStorage, WHEN the user selects the clear-saved-profile control, THE Web_Page SHALL remove the saved Household_Profile from localStorage and reset the form fields to empty.
8. FOR ALL valid Household_Profile objects, serializing to JSON for localStorage and then parsing SHALL produce a Household_Profile equal to the original in every field (round-trip property).
9. IF the saved localStorage data is not parseable JSON or is not a valid Household_Profile under criteria 2 and 3, THEN THE Web_Page SHALL ignore the saved data, display an empty form, and remove the invalid data from localStorage.

### Requirement 5: Deterministic impact table

**User Story:** As a user, I want to see the estimated effect of each action in numbers, so that I understand the direct impact of my choices.

#### Acceptance Criteria

1. WHEN a Household_Profile and an Air_Reading are provided, THE Impact_Engine SHALL compute an Impact_Table of 0 to 15 rows using fixed rules that depend only on the Household_Profile and the Air_Reading.
2. THE Impact_Engine SHALL include in each Impact_Table row an action, an estimated exposure-reduction percentage between 0 and 100 inclusive, an estimated CO2 kg/day saved between 0 and 100 inclusive, a basis of 1 to 200 characters, and a source note of 1 to 200 characters.
3. THE Impact_Engine SHALL mark every numeric value in the Impact_Table as approximate.
4. WHEN the Impact_Engine computes the Exposure_Score, THE Impact_Engine SHALL return a percentage between 0 and 100 inclusive that does not exceed the sum of the row exposure-reduction percentages.
5. WHEN the same Household_Profile and Air_Reading are provided twice, THE Impact_Engine SHALL return Impact_Tables with identical rows in identical order and identical Exposure_Scores.
6. WHERE the Commute_Mode is car or two_wheeler, THE Impact_Engine SHALL include a row for switching to bus_metro or walk_cycle.
7. WHERE the Cooking_Fuel is biomass, THE Impact_Engine SHALL include a row for switching to lpg, png, or induction.
8. WHERE the Heating_Type is biomass_burning, THE Impact_Engine SHALL include a row for switching to electric heating or additional insulation.
9. WHERE the Household_Profile indicates no purifier, THE Impact_Engine SHALL include a row for using a purifier or a low-cost DIY air-cleaning option.
10. WHEN the Impact_Table is available, THE Web_Page SHALL display for each row the action, the exposure-reduction percentage, the CO2 kg/day saved, the approximate marking, the basis, and the source note.
11. IF the Household_Profile or the Air_Reading is missing or contains a value outside its defined range, THEN THE Impact_Engine SHALL reject the request, return an error indicating which input is missing or invalid, and return no Impact_Table or Exposure_Score.
12. IF no row conditions in criteria 6 to 9 apply to the Household_Profile, THEN THE Impact_Engine SHALL return the Impact_Table built from the remaining rules (possibly with 0 rows) and an Exposure_Score of 0 when it has 0 rows, and THE Web_Page SHALL display a message indicating that no further actions apply when the table is empty.

### Requirement 6: Personalized plan generation with the LLM

**User Story:** As a parent, I want a clear daily plan tailored to my location and lifestyle, so that I can reduce my family's exposure without guesswork.

#### Acceptance Criteria

1. WHEN a user requests a Plan, THE Plan_Generator SHALL compute the Air_Reading and the Impact_Table and then make exactly one LLM_Client call, with no automatic retry of that call.
2. THE LLM_Client SHALL request structured JSON output containing the daily routine for morning, commute, midday, and evening, 1 to 5 indoor hacks, 1 to 5 sustainable swaps, and a vulnerable-members note of at most 500 characters.
3. THE LLM_Client SHALL provide the Impact_Table and Exposure_Score to the model and instruct the model to explain only the provided figures and not to introduce other numerical estimates.
4. THE Plan_Generator SHALL include a why-it-matters explanation of 1 to 300 characters for every routine item, indoor hack, and sustainable swap.
5. WHEN the LLM response is received, THE Plan_Generator SHALL validate the response against the Plan schema before returning the Plan.
6. IF the LLM call fails, does not return a response within the LLM_Timeout, or returns a response that fails Plan schema validation, THEN THE Plan_Generator SHALL return a Fallback_Plan with the fallback flag set to true, and the Impact_Table, Exposure_Score, and Air_Reading SHALL remain unchanged.
7. THE Plan_Generator SHALL replace every impact figure in the returned Plan with the figures from the Impact_Table, regardless of the LLM response content.
8. WHERE the Household_Profile or the Air_Reading makes a local context factor relevant, THE Plan_Generator SHALL include at least one routine item that addresses that factor, chosen from stubble burning, firecrackers, biomass cooking and heating, two-wheelers, and metro use.
9. WHERE the Household_Profile includes kids, elderly members, or a respiratory condition, THE Plan_Generator SHALL include a vulnerable-members note of 1 to 500 characters that names each vulnerable group present in the Household_Profile.
10. THE LLM_Client SHALL read the API key from the ANTHROPIC_API_KEY environment variable, the base URL from ANTHROPIC_BASE_URL, and the model name from LLM_MODEL, using claude-haiku-5-5 when LLM_MODEL is not set or is empty.
11. IF the ANTHROPIC_API_KEY environment variable is not set or is empty, THEN THE LLM_Client SHALL make no LLM call, and THE Plan_Generator SHALL return a Fallback_Plan with the fallback flag set to true.
12. WHEN a Plan request completes, THE Backend SHALL return the Plan, Air_Reading, Impact_Table, Exposure_Score, and a fallback flag in a single response, with the fallback flag set to false when the Plan came from a validated LLM response.
13. WHEN the Backend response is received, THE Web_Page SHALL display the Plan sections, the Air_Reading with CPCB_Band and indicative GRAP_Stage, and the Exposure_Score.

### Requirement 7: Plan fallback

**User Story:** As a user, I want to still receive useful advice when the AI service fails, so that I am not left without guidance.

#### Acceptance Criteria

1. IF the ANTHROPIC_API_KEY environment variable is missing or is an empty string, THEN THE Plan_Generator SHALL skip the LLM_Client call and return a Fallback_Plan.
2. IF the LLM_Client call raises an error, does not return a response within the LLM_Timeout, or returns output that cannot be parsed as JSON, THEN THE Plan_Generator SHALL return a Fallback_Plan.
3. IF the parsed LLM response fails validation against the Plan schema (a required field is missing or a field has the wrong type), THEN THE Plan_Generator SHALL return a Fallback_Plan.
4. WHEN the Plan_Generator returns a Fallback_Plan, THE Plan_Generator SHALL set the fallback flag to true.
5. WHEN the Plan_Generator returns a plan generated from a valid LLM response, THE Plan_Generator SHALL set the fallback flag to false.
6. THE Plan_Generator SHALL build the Fallback_Plan from the Impact_Table rows and the Household_Profile without calling the LLM_Client, and the Fallback_Plan SHALL pass validation against the same Plan schema as an LLM-generated plan.
7. WHEN a Fallback_Plan is displayed, THE Web_Page SHALL show a notice stating that the plan is rule-based and not AI-personalized, in the same view as the plan and without requiring user interaction to reveal it.
8. THE Plan_Generator SHALL make at most one LLM_Client call per Plan request, with no retries, including when the request ends in a Fallback_Plan.

### Requirement 8: Follow-up chat

**User Story:** As a user, I want to ask follow-up questions about my plan, so that I can understand and adapt the advice.

#### Acceptance Criteria

1. WHEN a user submits a message, THE Web_Page SHALL send a Chat_Request containing the Plan, Air_Reading, Household_Profile, chat history, and the message to the Backend.
2. THE Chat_Service SHALL answer using only the data in the Chat_Request and SHALL NOT store state between requests.
3. THE Chat_Service SHALL ground answers in the supplied Plan, Air_Reading, and Impact_Table and SHALL NOT state numerical estimates that are absent from them.
4. IF a user message is unrelated to air quality, pollution, or health-adjacent topics, THEN THE Chat_Service SHALL reply with a statement of at most 2 sentences that AirWise answers only air quality and related health questions.
5. WHEN a Chat_Service reply discusses health, THE Chat_Service SHALL include a not-medical-advice note in that reply.
6. IF a Chat_Request message is empty, consists only of whitespace, or is longer than 500 characters, THEN THE Backend SHALL reject the Chat_Request with a validation error indicating the message length rule, and THE Chat_Service SHALL NOT call the LLM_Client.
7. IF a Chat_Request contains more than 10 history entries, THEN THE Backend SHALL reject the Chat_Request with a validation error indicating the 10-entry history limit.
8. WHILE the chat history is empty and no user message has been submitted, THE Web_Page SHALL display between 3 and 5 suggested starter questions.
9. WHEN a user selects a starter question, THE Web_Page SHALL send the question text as the chat message in a Chat_Request and SHALL hide the starter questions after the request is sent.
10. IF the LLM_Client call for chat fails, exceeds the LLM_Timeout, or the API key is missing, THEN THE Chat_Service SHALL return a failure message that states the answer is unavailable and suggests trying again later, AND THE Web_Page SHALL display the message in the chat and keep the user's submitted message and existing chat history visible.
11. THE Chat_Service SHALL return each reply as a single complete response without streaming.

### Requirement 9: Input validation and size limits

**User Story:** As an operator, I want all inputs bounded and validated, so that the service is protected against malformed or oversized requests.

#### Acceptance Criteria

1. IF a request body does not conform to the defined schema for its endpoint, THEN THE Backend SHALL reject the request with HTTP status 422, return an error message that identifies each non-conforming field by name, and leave service state unchanged.
2. IF a request body exceeds 64 KB (65,536 bytes), THEN THE Backend SHALL reject the request with HTTP status 413 without processing the body, and return an error message indicating that the size limit was exceeded.
3. IF any string field in a Chat_Request exceeds its maximum length, THEN THE Backend SHALL reject the request with HTTP status 422 and return an error message that identifies the offending field. The maximum length is 500 characters for the user message, 2,000 characters for each chat history entry, 100 characters for the city, and 2,000 characters for every other string field.
4. IF a Chat_Request contains a Plan, Air_Reading, or Household_Profile that does not conform to its schema (including a missing required field, a wrong data type, or a numeric value outside its defined range), THEN THE Backend SHALL reject the request with HTTP status 422 and return an error message that identifies the non-conforming object and field.
5. IF a Chat_Request contains a collection field (list) with more than 50 items, THEN THE Backend SHALL reject the request with HTTP status 422 and return an error message that identifies the collection field.

### Requirement 10: Rate limiting

**User Story:** As an operator, I want per-client request limits, so that LLM costs and abuse are controlled.

#### Acceptance Criteria

1. WHEN a request arrives from a client IP address, THE Rate_Limiter SHALL count it against a separate fixed 60-second window for the plan endpoint (maximum 10 requests per window) or the chat endpoint (maximum 30 requests per window), tracked independently for each client IP address and each endpoint.
2. IF a client IP address submits an 11th plan request within its current 60-second plan window, or a 31st chat request within its current 60-second chat window, THEN THE Rate_Limiter SHALL reject that request with HTTP status 429, include a Retry-After header containing the whole number of seconds (1 to 60) until the window ends, and not forward the request to the LLM.
3. WHEN a client IP address's 60-second window elapses, THE Rate_Limiter SHALL reset that client IP address's count for that endpoint to 0 and accept requests from it again, up to the limit in criterion 1.
4. WHERE the X-Forwarded-For header is present and non-empty, THE Rate_Limiter SHALL use the first comma-separated entry, with surrounding whitespace removed, as the client IP address.
5. IF the X-Forwarded-For header is absent, empty, or its first entry is not a valid IPv4 or IPv6 address, THEN THE Rate_Limiter SHALL use the IP address of the direct network connection as the client IP address.

### Requirement 11: Security and secrets handling

**User Story:** As an operator, I want secrets and user content protected, so that credentials do not leak and the page is not exploitable.

#### Acceptance Criteria

1. THE Backend SHALL read the value of ANTHROPIC_API_KEY and any other credential only from process environment variables, and SHALL NOT read credentials from request payloads, query parameters, or source files committed to the repository.
2. THE Backend SHALL exclude the value of every secret (including ANTHROPIC_API_KEY) from log output, HTTP response bodies, HTTP response headers, and error messages.
3. WHEN the Web_Page inserts server-supplied or LLM-supplied text into the DOM, THE Web_Page SHALL insert the text as text nodes or as HTML-escaped text, so that the characters `<`, `>`, `&`, `"`, and `'` are displayed literally and are not interpreted as markup.
4. THE Web_Page SHALL NOT assign server-supplied or LLM-supplied text to innerHTML, outerHTML, or insertAdjacentHTML unless the text has first been HTML-escaped.
5. THE AirWise repository SHALL provide a .env.example file that lists the variable names ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL, and LLM_MODEL, each with an empty or placeholder value and no real credential.
6. IF an unexpected error occurs in the Backend, THEN THE Backend SHALL return an error response containing a generic message that indicates a server error occurred, SHALL NOT include stack traces, file paths, or secret values in the response, and SHALL leave previously stored data unchanged.
7. IF ANTHROPIC_API_KEY is missing or empty when a request requires it, THEN THE Backend SHALL NOT disclose the variable's value or any portion of it in any response, and SHALL handle the request as specified in Requirement 7 for plans and Requirement 8 for chat.

### Requirement 12: Deployment architecture

**User Story:** As a developer, I want a simple deployment with no build step or database, so that I can host AirWise on Vercel quickly.

#### Acceptance Criteria

1. THE Backend SHALL run as a Python FastAPI application on a Vercel serverless function, with all request handling contained in that single function and no process running outside a request.
2. THE Web_Page SHALL be a single HTML file that contains its own markup, styles, and vanilla JavaScript, SHALL load no JavaScript or CSS framework, and SHALL require no build, compile, or bundling command before deployment.
3. THE AirWise repository SHALL declare all Python dependencies in pyproject.toml and SHALL NOT contain a requirements.txt file.
4. THE AirWise repository SHALL provide a vercel.json that routes requests for API paths to the Backend and serves the Web_Page for the root path.
5. THE Backend SHALL store no data in a database and SHALL NOT require user accounts, sign-in, or session credentials for any request.
6. WHEN the Backend receives a plan request, THE Backend SHALL make exactly one LLM_Client call bounded by the LLM_Timeout and SHALL return its response before the Vercel function time limit is reached.
7. IF the LLM_Client call does not complete within the LLM_Timeout, THEN THE Backend SHALL abandon the call, make no further LLM_Client calls for that request, and return the Fallback_Plan for a plan request or the failure message for a chat request.
8. THE Backend SHALL use an LLM_Timeout value that is at least 2 seconds shorter than the configured Vercel function time limit, so that the fallback or failure response in criterion 7 is returned before the function is terminated.

### Requirement 13: Automated tests

**User Story:** As a developer, I want automated tests, so that I can change the code with confidence.

#### Acceptance Criteria

1. THE AirWise repository SHALL include pytest tests that contain at least one passing test case for each of the following areas: AQI computation, CPCB_Band assignment, GRAP_Stage assignment, Impact_Engine output, request validation, rate limiting, plan fallback, and chat behavior.
2. THE pytest tests SHALL mock the Open-Meteo APIs and the Anthropic API, and SHALL complete with zero outbound network connections and with no Anthropic API key set in the environment.
3. FOR ALL integer AQI values from 0 to 500 inclusive, THE tests SHALL verify that exactly one CPCB_Band is assigned and that each band boundary matches the ranges defined in Requirement 1.
4. FOR ALL valid Household_Profile and Air_Reading inputs, THE tests SHALL verify that the Impact_Engine returns identical output when called twice with the same input, and that the Exposure_Score is between 0 and 100 inclusive.
5. FOR ALL valid Plan objects, THE tests SHALL verify that serializing the Plan to JSON and parsing the result produces a Plan equal to the original in every field (round-trip property).
6. IF any pytest test fails, THEN THE test run SHALL exit with a non-zero exit code and report the name of each failing test.
7. WHEN the full pytest suite is run on a machine with no network access, THE test run SHALL finish within 60 seconds.

### Requirement 14: Documentation

**User Story:** As a developer, I want clear setup and deploy instructions, so that I can run and deploy AirWise.

#### Acceptance Criteria

1. THE AirWise repository SHALL include a README file at the repository root that contains a section for each of the following: feature set, local setup, environment variables, and running pytest.
2. THE README local setup section SHALL list, in numbered steps, the supported Python version, the dependency installation command, and the command that starts AirWise locally.
3. THE README environment variables section SHALL list every environment variable defined in `.env.example`, and for each variable SHALL state its name, whether it is required or optional, its purpose, and its default value if one exists.
4. THE README pytest section SHALL give the exact command that runs the full test suite from the repository root.
5. THE README SHALL include a Vercel deployment section with numbered steps covering: importing the repository into Vercel, setting the required ANTHROPIC_API_KEY environment variable, setting ANTHROPIC_BASE_URL if a gateway is used, optionally setting the LLM_MODEL environment variable, deploying, and confirming the deployment is working.
6. THE README Vercel deployment section SHALL state the default model that AirWise uses when LLM_MODEL is not set.
7. THE README SHALL contain a disclaimer section stating that (a) the impact figures are approximate, (b) the GRAP_Stage is indicative, and (c) AirWise does not provide medical advice.

### Requirement 15: Scope boundaries

**User Story:** As a stakeholder, I want the MVP scope stated, so that expectations are clear.

#### Acceptance Criteria

1. THE AirWise MVP SHALL render all user-facing text, including the Web_Page labels, advice content, and error messages, in English only.
2. THE AirWise MVP SHALL exclude user accounts (no sign-up, sign-in, or per-user profiles), database persistence (no user data or query history is stored after a response is returned), streaming responses (each response is delivered complete in a single reply), multiple languages (no language selector or non-English content), official GRAP declarations (no content stating that a GRAP stage has been officially declared or enforced by an authority), and medical advice (no diagnosis, treatment, or medication recommendations).
3. WHEN the Web_Page loads, THE Web_Page SHALL display a visible disclaimer stating that AirWise provides general information and not medical advice.
4. WHILE the Web_Page is displaying advice content, THE Web_Page SHALL keep the disclaimer visible on the page without requiring user interaction such as clicking, expanding, or scrolling more than one screen height from the advice content.
5. IF a user request asks for a diagnosis, treatment, medication, or an official GRAP declaration, THEN THE AirWise MVP SHALL decline to provide it, show a message indicating that the request is outside the scope of general information, and leave the current page state unchanged.