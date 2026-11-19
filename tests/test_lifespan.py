"""T4.2: the lifespan handler closes the shared Open-Meteo and LLM clients on shutdown."""

import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from airwise import main
from airwise.main import create_app
from airwise.services import llm
from tests.test_aqi_endpoint import AQ_OK, GEO_OK, make_handler
from tests.test_chat_validation import valid_payload

CHAT_OK = {
    "content": [
        {
            "type": "tool_use",
            "name": "chat",
            "input": {"reply": "The AQI is 300.", "on_topic": True, "discusses_health": False},
        }
    ]
}


@pytest.fixture(autouse=True)
def _fresh_module_clients(monkeypatch):
    """Start every test with no shared clients, and restore the module state afterwards."""
    monkeypatch.setattr(main, "_client", None)
    monkeypatch.setattr(main, "_client_loop", None)
    monkeypatch.setattr(llm, "_shared", None)


@pytest.fixture
def recorded_clients(monkeypatch):
    """Make the real get_http_client build recording AsyncClients backed by a MockTransport."""
    created: list[httpx.AsyncClient] = []
    handler = make_handler(geocode=GEO_OK, aq=AQ_OK)
    real = httpx.AsyncClient

    class Recording(real):  # type: ignore[valid-type, misc]
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)
            created.append(self)

    # Patch after create_app() is not required: main only calls httpx.AsyncClient at runtime.
    monkeypatch.setattr(httpx, "AsyncClient", Recording)
    return created


def _fail(exc: Exception):
    async def boom() -> None:
        raise exc

    return boom


def _recorder(log: list[str], name: str):
    async def close() -> None:
        log.append(name)

    return close


# a. nothing was ever created


def test_shutdown_with_no_clients_is_clean():
    with TestClient(create_app()) as c:
        assert c.get("/api/health").status_code == 200
    assert main._client is None
    assert llm._shared is None


# b. Open-Meteo client


def test_shutdown_closes_open_meteo_client(recorded_clients):
    with TestClient(create_app()) as c:
        r = c.get("/api/aqi", params={"city": "Delhi"})
        assert r.status_code == 200
        assert len(recorded_clients) == 1
        assert not recorded_clients[0].is_closed
        assert main._client is recorded_clients[0]
    assert recorded_clients[0].is_closed
    assert main._client is None
    assert main._client_loop is None


def test_shutdown_awaits_both_closers_exactly_once(monkeypatch):
    log: list[str] = []
    monkeypatch.setattr(main, "aclose_http_client", _recorder(log, "http"))
    monkeypatch.setattr(main, "aclose_llm_client", _recorder(log, "llm"))
    with TestClient(create_app()) as c:
        c.get("/api/health")
        assert log == []  # nothing happens before shutdown
    assert log == ["http", "llm"]


# c. LLM client


def test_shutdown_closes_llm_client(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setattr(
        llm, "_TRANSPORT", httpx.MockTransport(lambda request: httpx.Response(200, json=CHAT_OK))
    )
    with TestClient(create_app()) as c:
        r = c.post("/api/chat", json=valid_payload())
        assert r.status_code == 200
        assert r.json().get("failed") is not True
        assert llm._shared is not None
        shared_client = llm._shared[2]
        assert not shared_client.is_closed
    assert shared_client.is_closed
    assert llm._shared is None


# d. failure isolation


def test_http_close_failure_does_not_block_llm_close(monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="airwise")
    log: list[str] = []
    monkeypatch.setattr(main, "aclose_http_client", _fail(RuntimeError("secret detail")))
    monkeypatch.setattr(main, "aclose_llm_client", _recorder(log, "llm"))
    with TestClient(create_app()) as c:
        c.get("/api/health")
    assert log == ["llm"]
    assert "RuntimeError" in caplog.text
    assert "secret detail" not in caplog.text


def test_llm_close_failure_does_not_block_http_close(monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="airwise")
    log: list[str] = []
    monkeypatch.setattr(main, "aclose_http_client", _recorder(log, "http"))
    monkeypatch.setattr(main, "aclose_llm_client", _fail(ValueError("secret detail")))
    with TestClient(create_app()) as c:
        c.get("/api/health")
    assert log == ["http"]
    assert "ValueError" in caplog.text
    assert "secret detail" not in caplog.text


def test_cleanup_failure_does_not_mask_original_error(monkeypatch):
    monkeypatch.setattr(main, "aclose_http_client", _fail(RuntimeError("secret detail")))

    class Original(Exception):
        pass

    with pytest.raises(Original):
        with TestClient(create_app()):
            raise Original


# e. cross-loop safety


def test_client_from_closed_loop_is_replaced(recorded_clients):
    """Without lifespan every request runs in a new loop: a stale client must not be reused."""
    c = TestClient(create_app())  # no `with`: no lifespan, one fresh loop per request
    assert c.get("/api/aqi", params={"city": "Delhi"}).status_code == 200
    first = recorded_clients[0]
    assert c.get("/api/aqi", params={"city": "Delhi"}).status_code == 200
    assert len(recorded_clients) == 2
    assert main._client is recorded_clients[1] is not first


def test_second_testclient_context_gets_its_own_client(monkeypatch, recorded_clients):
    with TestClient(create_app()) as c:
        assert c.get("/api/aqi", params={"city": "Delhi"}).status_code == 200
        stale = main._client
        stale_loop = main._client_loop
    assert stale is recorded_clients[0] and stale.is_closed

    # Simulate a leftover from loop A whose shutdown never ran (closed loop, open client).
    monkeypatch.setattr(main, "_client", recorded_clients[0])
    monkeypatch.setattr(main, "_client_loop", stale_loop)
    with TestClient(create_app()) as c:
        r = c.get("/api/aqi", params={"city": "Delhi"})
        assert r.status_code == 200
        assert len(recorded_clients) == 2
        second = recorded_clients[1]
        assert main._client is second and not second.is_closed
    assert second.is_closed
    assert main._client is None


def test_aclose_http_client_from_other_loop_only_drops_reference(monkeypatch, recorded_clients):
    import asyncio

    with TestClient(create_app()) as c:
        c.get("/api/aqi", params={"city": "Delhi"})
        client, loop = main._client, main._client_loop
    # The with-block already closed it; put it back as if it belonged to a dead loop.
    monkeypatch.setattr(main, "_client", client)
    monkeypatch.setattr(main, "_client_loop", loop)
    asyncio.run(main.aclose_http_client())  # different loop: must not raise
    assert main._client is None and main._client_loop is None
    asyncio.run(main.aclose_http_client())  # nothing cached: no-op


# g. module-level app


def test_module_level_app_has_lifespan_configured():
    assert main.app.router.lifespan_context is main.lifespan
