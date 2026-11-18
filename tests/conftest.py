import socket

import pytest
from fastapi.testclient import TestClient

from airwise.main import create_app


@pytest.fixture(autouse=True)
def _isolate_env_and_network(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    real_connect = socket.socket.connect

    def _blocked(self, address, *args, **kwargs):
        # Loopback is allowed: Windows asyncio builds its self-pipe with it.
        if isinstance(address, tuple) and address and address[0] in ("127.0.0.1", "::1", "localhost"):
            return real_connect(self, address, *args, **kwargs)
        raise RuntimeError("Network access is blocked in tests")

    monkeypatch.setattr(socket.socket, "connect", _blocked)


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c
