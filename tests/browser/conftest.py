"""Browser test fixtures and configuration for Playwright."""

from __future__ import annotations

import json
import os
import re
import socket
import threading
import time
import urllib.request
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
import uvicorn

from airwise.main import create_app
from airwise.models import (
    AirReading,
    ChatReply,
    ImpactFigures,
    ImpactRow,
    Plan,
    PlanItem,
    PlanResponse,
    Routine,
)
from tests.browser.launch import REQUIRE_ENV, browser_unavailable, launch_chromium

ARTIFACT_DIR = Path("test-results")
_skipped: list[str] = []

DEFAULT_READING = AirReading(
    location_name="Delhi",
    latitude=28.6139,
    longitude=77.2090,
    pm2_5=185.0,
    pm10=310.0,
    aqi=350,
    band="Very Poor",
    grap_stage="Stage III",
    source="live",
)

DEFAULT_PLAN = Plan(
    routine=Routine(
        morning=[
            PlanItem(
                text="Keep windows closed during early morning peak smog hours.",
                why_it_matters="Morning temperature inversion traps PM2.5 near ground level.",
                impact_id="purifier_or_closed_windows",
                context_factor=None,
                impact=ImpactFigures(exposure_reduction_pct=35.0, co2_kg_per_day=0.0),
            )
        ],
        commute=[
            PlanItem(
                text="Use Metro or carpool instead of driving alone.",
                why_it_matters="Reduces individual vehicular emissions and cabin exposure.",
                impact_id="metro_commute",
                context_factor="metro_use",
                impact=ImpactFigures(exposure_reduction_pct=25.0, co2_kg_per_day=2.4),
            )
        ],
        midday=[
            PlanItem(
                text="Ventilate briefly between 1 PM and 3 PM when air quality is better.",
                why_it_matters="Sunlight and wind help disperse surface pollutants around midday.",
                impact_id=None,
                context_factor=None,
                impact=None,
            )
        ],
        evening=[
            PlanItem(
                text="Run indoor air purifier in bedroom before sleep.",
                why_it_matters="Reduces overnight PM2.5 inhalation during resting hours.",
                impact_id="purifier_or_closed_windows",
                context_factor=None,
                impact=ImpactFigures(exposure_reduction_pct=35.0, co2_kg_per_day=0.0),
            )
        ],
    ),
    indoor_hacks=[
        PlanItem(
            text="Use wet mopping instead of dry brooming to avoid resuspending settled dust.",
            why_it_matters="Dry sweeping kicks fine particulate matter back into breathing zones.",
            impact_id=None,
            context_factor=None,
            impact=None,
        )
    ],
    swaps=[
        PlanItem(
            text="Switch from biomass/coal heating to electric heater or warmer layers.",
            why_it_matters="Eliminates immediate indoor smoke and harmful combustion byproducts.",
            impact_id="electric_heating",
            context_factor="biomass_cooking_heating",
            impact=ImpactFigures(exposure_reduction_pct=40.0, co2_kg_per_day=1.8),
        )
    ],
    vulnerable_note="Take extra precautions for children and elderly members.",
    impact_table=[
        ImpactRow(
            id="purifier_or_closed_windows",
            action="Run HEPA air purifier or keep windows mostly closed during peak hours",
            exposure_reduction_pct=35.0,
            co2_kg_per_day=0.0,
            basis="HEPA filtration and physical barrier against ambient PM2.5 infiltration",
            source_note="CPCB indoor air quality advisory & WHO exposure guidelines",
        ),
        ImpactRow(
            id="metro_commute",
            action="Switch commute from private vehicle to Delhi Metro",
            exposure_reduction_pct=25.0,
            co2_kg_per_day=2.4,
            basis="Underground/AC cabin filtration and avoided fuel combustion",
            source_note="TERI urban mobility emission factors",
        ),
    ],
    exposure_score=45.0,
    fallback=False,
    estimated=False,
)

DEFAULT_PLAN_RESPONSE = PlanResponse(
    plan=DEFAULT_PLAN,
    reading=DEFAULT_READING,
)

DEFAULT_CHAT_REPLY = ChatReply(
    reply="To minimize exposure today, keep windows closed during peak morning smog hours.",
    failed=False,
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        fspath_parts = Path(str(item.fspath)).parts
        if "browser" in fspath_parts:
            item.add_marker(pytest.mark.browser)


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.skipped:
        _skipped.append(report.nodeid)


def pytest_sessionfinish(session: pytest.Session) -> None:
    """With AIRWISE_REQUIRE_BROWSER=1 (CI) a browser run with any skipped test is a failure."""
    if os.environ.get(REQUIRE_ENV) == "1" and _skipped and session.exitstatus == 0:
        print(f"\n{REQUIRE_ENV}=1: {len(_skipped)} browser test(s) skipped; failing the run.")
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def save_failure_artifacts(page: Any, nodeid: str) -> None:
    """Save a screenshot and the page HTML to test-results/ (git-ignored); never raises.

    Pages only ever show the local app with mocked APIs, so no secrets are captured.
    """
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", nodeid).strip("_")[-150:]
    try:
        ARTIFACT_DIR.mkdir(exist_ok=True)
        page.screenshot(path=str(ARTIFACT_DIR / f"{stem}.png"), full_page=True)
        (ARTIFACT_DIR / f"{stem}.html").write_text(page.content(), encoding="utf-8")
    except Exception:
        pass


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, Any, None]:
    outcome = yield
    report = outcome.get_result()
    if report.when == "call" and report.failed:
        page = getattr(item, "funcargs", {}).get("page")
        if page is not None:
            save_failure_artifacts(page, item.nodeid)


class RecordedRequest:
    def __init__(self, method: str, url: str, post_data: str | None = None) -> None:
        self.method = method
        self.url = url
        self.post_data = post_data
        self._json: Any = None
        if post_data:
            try:
                self._json = json.loads(post_data)
            except Exception:
                pass

    @property
    def json(self) -> Any:
        return self._json


class HoldController:
    """Controller for held route requests, allowing non-blocking assertions while in flight."""

    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint
        self._held: list[tuple[Any, int, dict[str, Any], dict[str, str]]] = []
        self._released = False

    def capture(
        self,
        route: Any,
        default_status: int,
        default_body: dict[str, Any],
        default_headers: dict[str, str] | None = None,
    ) -> None:
        if self._released:
            route.fulfill(
                status=default_status,
                headers=default_headers or None,
                content_type="application/json; charset=utf-8",
                body=json.dumps(default_body),
            )
        else:
            self._held.append((route, default_status, default_body, default_headers or {}))

    def release(
        self,
        *,
        status: int | None = None,
        body: dict[str, Any] | str | None = None,
        headers: dict[str, str] | None = None,
        abort: bool = False,
    ) -> None:
        """Release all held requests for this endpoint."""
        self._released = True
        for route, def_status, def_body, def_headers in self._held:
            if abort:
                route.abort()
            else:
                resp_status = status if status is not None else def_status
                resp_headers = headers if headers is not None else def_headers
                if body is not None:
                    resp_body = body if isinstance(body, str) else json.dumps(body)
                else:
                    resp_body = json.dumps(def_body)
                route.fulfill(
                    status=resp_status,
                    headers=resp_headers or None,
                    content_type="application/json; charset=utf-8",
                    body=resp_body,
                )
        self._held.clear()


class MockApi:
    """Mock API helper for Playwright tests, intercepting /api/* calls."""

    def __init__(self, live_server: str, page: Any) -> None:
        self.live_server = live_server
        self.page = page
        self.requests: list[RecordedRequest] = []
        self._holds: dict[str, HoldController] = {}

        self.aqi_response: dict[str, Any] = json.loads(DEFAULT_READING.model_dump_json())
        self.aqi_status: int = 200
        self.aqi_headers: dict[str, str] = {}

        self.plan_response: dict[str, Any] = json.loads(DEFAULT_PLAN_RESPONSE.model_dump_json())
        self.plan_status: int = 200
        self.plan_headers: dict[str, str] = {}

        self.chat_response: dict[str, Any] = json.loads(DEFAULT_CHAT_REPLY.model_dump_json())
        self.chat_status: int = 200
        self.chat_headers: dict[str, str] = {}

    def hold(self, endpoint: str) -> HoldController:
        """Register a non-blocking gate that intercepts requests without completing them."""
        controller = HoldController(endpoint)
        self._holds[endpoint] = controller
        return controller

    def set_aqi(
        self,
        reading: AirReading | dict[str, Any],
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        if isinstance(reading, AirReading):
            self.aqi_response = json.loads(reading.model_dump_json())
        else:
            self.aqi_response = reading
        self.aqi_status = status
        self.aqi_headers = headers or {}

    def set_plan(
        self,
        plan_response: PlanResponse | dict[str, Any],
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        if isinstance(plan_response, PlanResponse):
            self.plan_response = json.loads(plan_response.model_dump_json())
        else:
            self.plan_response = plan_response
        self.plan_status = status
        self.plan_headers = headers or {}

    def set_chat(
        self,
        chat_reply: ChatReply | dict[str, Any],
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        if isinstance(chat_reply, ChatReply):
            self.chat_response = json.loads(chat_reply.model_dump_json())
        else:
            self.chat_response = chat_reply
        self.chat_status = status
        self.chat_headers = headers or {}

    def install(self) -> None:
        def handler(route: Any, request: Any) -> None:
            url: str = request.url
            method: str = request.method
            post_data: str | None = request.post_data

            # Allow live server static assets and health check
            if url.startswith(self.live_server):
                path = url[len(self.live_server) :]
                if path in (
                    "/",
                    "/app.css",
                    "/app.js",
                    "/favicon.ico",
                    "/api/health",
                ) or path.startswith("/?"):
                    route.continue_()
                    return

            # Mock /api/aqi
            if "/api/aqi" in url:
                self.requests.append(RecordedRequest(method=method, url=url, post_data=post_data))
                if "aqi" in self._holds:
                    self._holds["aqi"].capture(
                        route, self.aqi_status, self.aqi_response, self.aqi_headers
                    )
                else:
                    route.fulfill(
                        status=self.aqi_status,
                        headers=self.aqi_headers or None,
                        content_type="application/json; charset=utf-8",
                        body=json.dumps(self.aqi_response),
                    )
                return

            # Mock /api/plan
            if "/api/plan" in url:
                self.requests.append(RecordedRequest(method=method, url=url, post_data=post_data))
                if "plan" in self._holds:
                    self._holds["plan"].capture(
                        route, self.plan_status, self.plan_response, self.plan_headers
                    )
                else:
                    route.fulfill(
                        status=self.plan_status,
                        headers=self.plan_headers or None,
                        content_type="application/json; charset=utf-8",
                        body=json.dumps(self.plan_response),
                    )
                return

            # Mock /api/chat
            if "/api/chat" in url:
                self.requests.append(RecordedRequest(method=method, url=url, post_data=post_data))
                if "chat" in self._holds:
                    self._holds["chat"].capture(
                        route, self.chat_status, self.chat_response, self.chat_headers
                    )
                else:
                    route.fulfill(
                        status=self.chat_status,
                        headers=self.chat_headers or None,
                        content_type="application/json; charset=utf-8",
                        body=json.dumps(self.chat_response),
                    )
                return

            # Abort any unexpected external or unhandled request
            route.abort()

        self.page.route("**/*", handler)


@pytest.fixture(scope="session")
def live_server() -> Generator[str, None, None]:
    """Starts the real FastAPI app bound to 127.0.0.1 on an ephemeral port in a hermetic env."""
    mp = pytest.MonkeyPatch()
    mp.delenv("ANTHROPIC_API_KEY", raising=False)
    mp.delenv("LLM_MODEL", raising=False)
    mp.delenv("ANTHROPIC_BASE_URL", raising=False)
    mp.setattr("airwise.config.ENV_FILE", Path("__no_such_env_file__"))

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    app = create_app()
    config = uvicorn.Config(app=app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 5.0
    started = False
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/api/health", timeout=0.5) as resp:
                if resp.status == 200:
                    started = True
                    break
        except Exception:
            time.sleep(0.05)

    if not started:
        server.should_exit = True
        thread.join(timeout=2.0)
        mp.undo()
        raise RuntimeError(f"live_server failed to start on {base_url}")

    try:
        yield base_url
    finally:
        server.should_exit = True
        thread.join(timeout=5.0)
        mp.undo()


@pytest.fixture
def browser() -> Generator[Any, None, None]:
    """Launches Playwright Chromium (bundled or system fallback).

    Skips when no browser is available, or fails if AIRWISE_REQUIRE_BROWSER=1 (CI).
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        browser_unavailable("Playwright is not installed.")
        return

    with sync_playwright() as p:
        launched_browser = launch_chromium(p)
        yield launched_browser
        launched_browser.close()


@pytest.fixture
def page(
    browser: Any, live_server: str, request: pytest.FixtureRequest
) -> Generator[Any, None, None]:
    """Provides an isolated browser page per test with console error and CSP monitoring."""
    context = browser.new_context(
        viewport={"width": 1280, "height": 800},
        locale="en-IN",
        accept_downloads=False,
        service_workers="block",
    )
    p = context.new_page()

    console_errors: list[str] = []
    page_errors: list[str] = []

    def on_console(msg: Any) -> None:
        if msg.type == "error":
            # Chromium console logs HTTP 4xx/5xx responses and aborted fetches as
            # "Failed to load resource: the server responded with a status of ..."
            if msg.text.startswith("Failed to load resource:"):
                return
            console_errors.append(msg.text)

    def on_pageerror(err: Any) -> None:
        page_errors.append(str(err))

    p.on("console", on_console)
    p.on("pageerror", on_pageerror)

    p.add_init_script(
        """
        window.__csp_violations = [];
        document.addEventListener('securitypolicyviolation', function(e) {
            window.__csp_violations.push({
                blockedURI: e.blockedURI,
                violatedDirective: e.violatedDirective,
                originalPolicy: e.originalPolicy
            });
        });
        """
    )

    yield p

    csp_violations: list[dict[str, Any]] = []
    try:
        csp_violations = p.evaluate("() => window.__csp_violations || []")
    except Exception:
        pass

    if console_errors or page_errors or csp_violations:
        save_failure_artifacts(p, request.node.nodeid)
    context.close()

    if console_errors:
        pytest.fail(f"Unexpected console errors: {console_errors}")
    if page_errors:
        pytest.fail(f"Unexpected page errors: {page_errors}")
    if csp_violations:
        pytest.fail(f"CSP violations detected: {csp_violations}")


@pytest.fixture
def mock_api(page: Any, live_server: str) -> MockApi:
    """Helper that registers route handlers for /api/* and records requests."""
    helper = MockApi(live_server=live_server, page=page)
    helper.install()
    return helper
