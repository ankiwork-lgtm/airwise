# AirWise Code Quality Elevation Plan (One-by-One Execution)

This plan provides an incremental, risk-controlled roadmap to resolve all remaining code smells, type ignores, exception-handling anti-patterns, and documentation gaps. Each step is isolated and verified independently so the codebase remains 100% green at every step.

---

## Plan Overview & Execution Principles

1. **One Step at a Time**: Each task is a self-contained unit of work with specific target files, diff specifications, and automated verification commands.
2. **Zero Regressions**: Baseline test coverage (100.00% statements and branches, 454 tests) and all existing contract behaviors must remain unbroken after every step.
3. **No Unhandled Side Effects**: If any test fails, changes for that step are rolled back before investigating.

---

## Step-by-Step Task Breakdown

### Step 1: Eliminate `# type: ignore` in Exception Handlers [COMPLETED]
- **Status**: Done (commit-ready)
- **Goal**: Achieve 100% strict type safety without suppression comments in error handling.
- **Target Files**:
  - `airwise/handlers.py`
  - `tests/test_coverage_edge_cases.py`
- **Actions**:
  1. Update `app_error_handler(request: Request, exc: Exception)` and `validation_error_handler(request: Request, exc: Exception)` signatures to accept `Exception`.
  2. Inside `app_error_handler`, use type narrowing: `assert isinstance(exc, AppError)` or `if isinstance(exc, AppError):`.
  3. Inside `validation_error_handler`, use type narrowing: `assert isinstance(exc, RequestValidationError)`.
  4. Remove the `# type: ignore[arg-type]` comments on `app.add_exception_handler` calls in `register_exception_handlers()`.
  5. Remove the `# type: ignore[arg-type]` in `tests/test_coverage_edge_cases.py:53`.
- **Verification**:
  ```powershell
  & .venv\Scripts\mypy.exe airwise
  & .venv\Scripts\pytest.exe tests/test_coverage_edge_cases.py
  ```

---

### Step 2: Enrich OpenAPI Route Metadata & Error Responses [COMPLETED]
- **Status**: Done (commit-ready)
- **Goal**: Enable self-documenting Swagger/ReDoc schemas with complete tags, summaries, descriptions, and error status models.
- **Target Files**:
  - `airwise/routes/aqi.py`
  - `airwise/routes/plan.py`
  - `airwise/routes/chat.py`
  - `airwise/routes/health.py`
- **Actions**:
  1. Add `tags=["Air Quality"]`, `summary=...`, `description=...` to `GET /api/aqi`.
  2. Add `tags=["Plan Generation"]`, `summary=...`, `description=...` to `POST /api/plan`.
  3. Add `tags=["Assistant Chat"]`, `summary=...`, `description=...` to `POST /api/chat`.
  4. Add `tags=["Health"]`, `summary=...`, `description=...` to `GET /api/health`.
  5. Add explicit `responses` dictionaries declaring standard status codes:
     - `413`: Payload Too Large (body > 64 KB)
     - `422`: Validation Error (invalid city, out-of-range coordinates)
     - `429`: Rate Limited (with Retry-After header)
     - `502`: Upstream Lookup Unavailable
- **Verification**:
  ```powershell
  & .venv\Scripts\pytest.exe tests/test_aqi_endpoint.py tests/test_plan_coordinates.py tests/test_health.py
  & .venv\Scripts\mypy.exe airwise
  ```

---

### Step 3: Replace Broad `except Exception:` with Specific Exceptions [COMPLETED]
- **Status**: Done (commit-ready)
- **Goal**: Eliminate `BLE001` (blind except) to ensure unexpected bugs or loop cancellations are not swallowed silently.
- **Target Files**:
  - `airwise/services/plan.py`
  - `airwise/services/chat.py`
  - `airwise/services/llm.py`
- **Actions**:
  1. In `airwise/services/plan.py:145`: Replace `except Exception as exc:` with:
     ```python
     except (LLMUnavailable, httpx.HTTPError, ValidationError, TimeoutError) as exc:
     ```
  2. In `airwise/services/chat.py:125`: Replace `except Exception as exc:` with:
     ```python
     except (LLMUnavailable, httpx.HTTPError, ValidationError, TimeoutError) as exc:
     ```
  3. In `airwise/services/llm.py:117`: Replace `except Exception as exc:` with:
     ```python
     except (httpx.HTTPError, json.JSONDecodeError, TimeoutError) as exc:
     ```
- **Verification**:
  ```powershell
  & .venv\Scripts\pytest.exe tests/test_plan_llm_outcomes.py tests/test_chat_properties.py tests/test_error_hygiene.py
  & .venv\Scripts\ruff.exe check airwise
  ```

---

### Step 4: Expand Public Service Functions to Full Google-Style Docstrings [COMPLETED]
- **Status**: Done (commit-ready)
- **Goal**: Satisfy rigorous docstring completeness linters (Sphinx / Darglint / Google style) with explicit parameter types, return values, and exceptions raised.
- **Target Files**:
  - `airwise/services/aqi.py`
  - `airwise/services/plan.py`
  - `airwise/services/chat.py`
  - `airwise/services/impact.py`
- **Actions**:
  1. In `airwise/services/aqi.py`: Expand docstrings for `sub_index`, `compute_aqi`, `band_for`, `grap_for`, `fetch_pm`, and `get_reading` with:
     - `Args:`
     - `Returns:`
     - `Raises:`
  2. In `airwise/services/plan.py`: Expand docstrings for `generate_plan`, `build_vulnerable_note`, `context_factors`.
  3. In `airwise/services/chat.py`: Expand docstring for `answer`.
  4. In `airwise/services/impact.py`: Expand docstrings for `compute_impact` and rule helper functions.
- **Verification**:
  ```powershell
  & .venv\Scripts\ruff.exe check .
  & .venv\Scripts\ruff.exe format --check .
  ```

---

### Step 5: Encapsulate Shared Clients into Loop-Safe Container (`PLW0603`) [COMPLETED]
- **Goal**: Eliminate naked module-level `global _client` and `global _shared` variables while keeping test injection hooks intact.
- **Target Files**:
  - `airwise/main.py`
  - `airwise/services/llm.py`
  - `tests/test_lifespan.py`
  - `tests/test_llm_client.py`
- **Actions**:
  1. Created `HttpClientContainer` class in `airwise/main.py` that encapsulates `client` and `loop`.
  2. Exposed `get_http_client()` and `aclose_http_client()` delegation methods on the container.
  3. In `airwise/services/llm.py`, created `LLMClientCache` class managing lazy client creation and event loop verification.
  4. Preserved `app.dependency_overrides[get_http_client]` and the test monkeypatching hook `llm._TRANSPORT`.
  5. Removed `# noqa: PLW0603` comments across both files.
- **Verification**:
  ```powershell
  & .venv\Scripts\pytest.exe tests/test_lifespan.py tests/test_llm_client.py tests/test_coverage_edge_cases.py
  & .venv\Scripts\ruff.exe check .
  ```

---

### Step 6: Import Hygiene with `TYPE_CHECKING` Guards [COMPLETED]
- **Goal**: Minimize circular import surface and reduce cold-start execution time by isolating type-only imports.
- **Target Files**:
  - `airwise/handlers.py`
  - `airwise/main.py`
  - `airwise/services/llm.py`
- **Actions**:
  1. Wrapped type-only imports (`AsyncIterator`, `Request`, `FastAPI`, `LLMClient`, `AirReading`, `HouseholdProfile`, `ImpactRow`) in `if TYPE_CHECKING:` blocks.
  2. Maintained `from __future__ import annotations` across all modified files for postponed evaluation of annotations.
- **Verification**:
  ```powershell
  & .venv\Scripts\mypy.exe airwise
  & .venv\Scripts\pytest.exe -m "not browser"
  ```

---

### Step 7: Modernize Frontend JavaScript (`public/app.js`) with Synchronized Test Updates [COMPLETED]
- **Goal**: Upgrade legacy ES5 `var` declarations to modern ES6 `const` and `let` while keeping all static string tests green.
- **Target Files**:
  - `public/app.js`
  - `tests/test_static_aria.py`
  - `tests/test_static_chat.py`
  - `tests/test_static_chat_ui.py`
  - `tests/test_static_results.py`
  - `tests/browser/test_chat.py`
- **Actions**:
  1. Converted all 126 `var` declarations in `public/app.js` to modern ES6 `const` (116 declarations) and block-scoped `let` (10 reassigned declarations).
  2. Synchronized static and browser test string assertions matching `var CONSTANT_NAME` and `var variable` across `tests/test_static_aria.py`, `tests/test_static_chat.py`, `tests/test_static_chat_ui.py`, `tests/test_static_results.py`, and `tests/browser/test_chat.py`.
- **Verification**:
  ```powershell
  & .venv\Scripts\pytest.exe -k "test_static"
  & .venv\Scripts\pytest.exe tests/browser -m browser
  ```

---

### Step 8: Full Quality Gate & Final Benchmark Verification [COMPLETED]
- **Goal**: Confirm all linters, type checkers, security scanners, and test suites pass with 100.00% coverage.
- **Verification Suite Results**:
  1. **Static Linting & Formatting**: Ruff `check .` and `format --check .` passed cleanly (0 errors, 77 files checked).
  2. **Strict Type Checking**: Mypy passed with 0 issues across all 21 source files in strict mode.
  3. **Unit / Integration Suite & Coverage**: All 357 fast tests passed with 100.00% statement (1031/1031) and branch (190/190) coverage.
  4. **Playwright Browser E2E Suite**: All 97 browser tests passed (axe WCAG 2.1 AA audits, keyboard navigation, full live server integration).
  5. **Dependency Vulnerability Audit**: `pip-audit --require-hashes --strict` reported 0 known vulnerabilities.
- **Success Criteria**:
  - Total statements & branches: 100.00% covered (0 missed lines, 0 missed branches).
  - All 454/454 tests passing.
  - Plan fully executed and pushed to `origin/main`.
  - Zero warnings, zero type ignores, zero security vulnerabilities.
