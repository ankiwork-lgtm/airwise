"""Targeted tests to cover edge cases, defensive branches and ensure 100% test coverage."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.exceptions import RequestValidationError

from airwise.config import load_env_file
from airwise.errors import InvalidCity
from airwise.handlers import validation_error_handler
from airwise.main import aclose_http_client, get_http_client
from airwise.middleware import BodySizeLimitMiddleware
from airwise.models import AirReading, HouseholdProfile, PlanItem
from airwise.services import aqi as aqi_service
from airwise.services.llm import AnthropicClient, LLMUnavailable
from airwise.services.plan import ensure_local_context, ensure_vulnerable_note


def test_load_env_file_with_quotes_and_edge_lines(tmp_path, monkeypatch):
    env_content = """
    # comment
    KEY1="double_quoted_value"
    KEY2='single_quoted_value'
    KEY3=unquoted_value
    =missing_key
    INVALID_LINE_WITHOUT_EQUALS
    KEY4=""
    """
    env_file = tmp_path / ".env"
    env_file.write_text(env_content, encoding="utf-8")
    monkeypatch.setattr("airwise.config.ENV_FILE", env_file)

    load_env_file()
    import os

    assert os.environ.get("KEY1") == "double_quoted_value"
    assert os.environ.get("KEY2") == "single_quoted_value"
    assert os.environ.get("KEY3") == "unquoted_value"


@pytest.mark.anyio
async def test_validation_error_handler_deduplicates_same_field():
    exc = RequestValidationError(
        [
            {"type": "value_error", "loc": ("body", "profile", "city"), "msg": "err1"},
            {"type": "string_too_short", "loc": ("body", "profile", "city"), "msg": "err2"},
        ]
    )
    from starlette.requests import Request as StarletteRequest

    scope = {"type": "http", "method": "GET", "path": "/"}
    resp = await validation_error_handler(StarletteRequest(scope), exc)
    data = json.loads(resp.body.decode("utf-8"))
    assert data["error"]["fields"] == ["profile.city"]


@pytest.mark.anyio
async def test_get_http_client_reuses_existing_client():
    await aclose_http_client()
    client1 = await get_http_client()
    client2 = await get_http_client()
    assert client1 is client2
    await aclose_http_client()


@pytest.mark.anyio
async def test_body_limit_middleware_invalid_content_length():
    app = AsyncMock()
    middleware = BodySizeLimitMiddleware(app, max_bytes=100)

    scope = {
        "type": "http",
        "headers": [(b"content-length", b"not-a-number")],
    }

    async def receive():
        return {"type": "http.request", "body": b"hello", "more_body": False}

    async def send(message):
        pass

    await middleware(scope, receive, send)
    assert app.called


@pytest.mark.anyio
async def test_body_limit_middleware_disconnect_during_stream():
    app = AsyncMock()
    middleware = BodySizeLimitMiddleware(app, max_bytes=100)

    scope = {
        "type": "http",
        "headers": [],
    }

    async def receive():
        return {"type": "http.disconnect"}

    async def send(message):
        pass

    await middleware(scope, receive, send)
    assert app.called


def test_compute_aqi_value_error_when_no_pm():
    with pytest.raises(ValueError, match="at least one of pm25 or pm10 is required"):
        aqi_service.compute_aqi(None, None)


def test_num_helper_edge_cases():
    assert aqi_service._num(float("nan")) is None
    assert aqi_service._num(-10.0) is None
    assert aqi_service._num(6000.0) is None
    assert aqi_service._num(True) is None
    assert aqi_service._num("123") is None
    assert aqi_service._num(45.5) == 45.5


def test_observed_at_helper_edge_cases():
    assert aqi_service._observed_at(123) is None
    assert aqi_service._observed_at("not-a-date") is None
    # Offset-aware ISO string
    res = aqi_service._observed_at("2025-01-15T09:00:00+00:00")
    assert res == "2025-01-15T09:00:00Z"
    # Naive ISO string
    res_naive = aqi_service._observed_at("2025-01-15T09:00:00")
    assert res_naive == "2025-01-15T09:00:00Z"


@pytest.mark.anyio
async def test_geocode_upstream_malformed_and_out_of_bounds():
    # Malformed data missing latitude
    mock_resp_malformed = httpx.Response(
        200,
        json={"results": [{"name": "Delhi"}]},
        request=httpx.Request("GET", "https://example.com"),
    )
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get = AsyncMock(return_value=mock_resp_malformed)
    with pytest.raises(aqi_service.LookupUnavailable):
        await aqi_service._geocode_upstream(client, "Delhi")

    # Out of bounds lat
    mock_resp_oob = httpx.Response(
        200,
        json={"results": [{"name": "Delhi", "latitude": 95.0, "longitude": 77.0}]},
        request=httpx.Request("GET", "https://example.com"),
    )
    client.get = AsyncMock(return_value=mock_resp_oob)
    with pytest.raises(aqi_service.LookupUnavailable):
        await aqi_service._geocode_upstream(client, "Delhi")


@pytest.mark.anyio
async def test_get_reading_invalid_city_when_neither_city_nor_coords():
    client = AsyncMock(spec=httpx.AsyncClient)
    with pytest.raises(InvalidCity):
        await aqi_service.get_reading(client, city=None, lat=None, lon=None)


@pytest.mark.anyio
async def test_anthropic_client_call_reraises_llm_unavailable_and_rejects_non_dict(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    client = AnthropicClient()

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = LLMUnavailable("test error")
    with patch("airwise.services.llm._get_client", return_value=mock_client):
        with pytest.raises(LLMUnavailable):
            await client.complete_json(
                system="sys", user="usr", schema={}, schema_name="s", timeout_s=5.0
            )

    # Tool use block input is not a dict
    mock_resp = httpx.Response(
        200,
        json={"content": [{"type": "tool_use", "name": "s", "input": "not-a-dict"}]},
        request=httpx.Request("POST", "https://example.com"),
    )
    mock_client.post = AsyncMock(return_value=mock_resp)
    with patch("airwise.services.llm._get_client", return_value=mock_client):
        with pytest.raises(LLMUnavailable, match="non-object response"):
            await client.complete_json(
                system="sys", user="usr", schema={}, schema_name="s", timeout_s=5.0
            )


def test_ensure_vulnerable_note_all_groups_present_and_zero_room():
    profile = HouseholdProfile(
        city="Delhi",
        kids=True,
        elderly=True,
        respiratory=True,
        commute="car",
        cooking_fuel="lpg",
        heating="electric",
        has_purifier=True,
        ventilation="open_often",
    )
    # When note already mentions all vulnerable groups
    existing = "Guidance for kids, elderly members and respiratory conditions."
    assert ensure_vulnerable_note(profile, existing) == existing

    # When room <= 0
    with patch("airwise.services.plan.build_vulnerable_note", return_value="X" * 500):
        res = ensure_vulnerable_note(profile, "Some base note")
        assert res == "X" * 500


def test_ensure_local_context_replaces_midday_when_slots_full():
    profile = HouseholdProfile(
        city="Delhi",
        kids=False,
        elderly=False,
        respiratory=False,
        commute="two_wheeler",
        cooking_fuel="lpg",
        heating="none",
        has_purifier=False,
        ventilation="open_often",
    )
    reading = AirReading(
        location_name="Delhi",
        latitude=28.6,
        longitude=77.2,
        pm2_5=250.0,
        pm10=400.0,
        aqi=350,
        band="Very Poor",
        grap_stage="Stage II",
        source="live",
    )
    # Fill all slots with 3 items each
    dummy_item = PlanItem(text="Action", why_it_matters="Why")
    routine = {
        "morning": [dummy_item, dummy_item, dummy_item],
        "commute": [dummy_item, dummy_item, dummy_item],
        "midday": [
            dummy_item,
            dummy_item,
            PlanItem(text="Old Midday", why_it_matters="Old Midday Why"),
        ],
        "evening": [dummy_item, dummy_item, dummy_item],
    }
    ensure_local_context(profile, reading, routine)
    assert routine["midday"][-1].context_factor is not None
