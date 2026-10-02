from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
import respx
from mcp import Client
from mcp.types import CallToolResult, TextContent

from invoiceninja_mcp.client import InvoiceNinjaClient
from invoiceninja_mcp.config import Settings
from invoiceninja_mcp.server import build_server

API = "https://ninja.example.com/api/v1"

CallTool = Callable[..., Awaitable[CallToolResult]]


def text_of(result: CallToolResult) -> str:
    return "\n".join(c.text for c in result.content if isinstance(c, TextContent))


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {"base_url": "https://ninja.example.com", "api_token": "tok-123"}
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def api() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=API, assert_all_called=False) as router:
        yield router


@asynccontextmanager
async def _session(settings: Settings) -> AsyncIterator[Client]:
    async with InvoiceNinjaClient(settings) as http:
        server = build_server(settings, client=http, report_poll_interval=0)
        async with Client(server) as client:
            yield client


@pytest.fixture
async def mcp_client(api: respx.MockRouter) -> AsyncIterator[Client]:
    async with _session(make_settings()) as c:
        yield c


@pytest.fixture
async def mcp_client_rw(api: respx.MockRouter) -> AsyncIterator[Client]:
    async with _session(make_settings(enable_writes=True)) as c:
        yield c
