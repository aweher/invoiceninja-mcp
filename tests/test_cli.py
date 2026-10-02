from typing import Any

import pytest
from mcp.server import MCPServer

from invoiceninja_mcp import server as server_module

ENV = {"INVOICENINJA_URL": "https://ninja.example.com", "INVOICENINJA_API_TOKEN": "tok"}


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for key in ("INVOICENINJA_URL", "INVOICENINJA_API_TOKEN", "INVOICENINJA_ENABLE_WRITES"):
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


@pytest.fixture
def runs(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_run(self: MCPServer, transport: str = "stdio", **kwargs: Any) -> None:
        calls.append((transport, kwargs))

    monkeypatch.setattr(MCPServer, "run", fake_run)
    return calls


def test_missing_config_exits_with_code_2(
    env: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        server_module.main([])
    assert exc.value.code == 2
    assert "INVOICENINJA_URL" in capsys.readouterr().err


def test_runs_stdio_by_default(
    env: pytest.MonkeyPatch, runs: list[tuple[str, dict[str, Any]]]
) -> None:
    for key, value in ENV.items():
        env.setenv(key, value)
    server_module.main([])
    assert runs == [("stdio", {})]


def test_runs_streamable_http(
    env: pytest.MonkeyPatch,
    runs: list[tuple[str, dict[str, Any]]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    for key, value in ENV.items():
        env.setenv(key, value)
    server_module.main(["--transport", "streamable-http", "--port", "9000"])
    transport, kwargs = runs[0]
    assert transport == "streamable-http"
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 9000
    assert "WARNING" not in capsys.readouterr().err


def test_warns_when_http_is_exposed(
    env: pytest.MonkeyPatch,
    runs: list[tuple[str, dict[str, Any]]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    for key, value in ENV.items():
        env.setenv(key, value)
    server_module.main(["--transport", "streamable-http", "--host", "0.0.0.0"])
    assert "WARNING" in capsys.readouterr().err
