"""Read-only smoke tests against a real instance.

Run with: INVOICENINJA_URL=... INVOICENINJA_API_TOKEN=... uv run pytest -m live
(the public demo works: https://demo.invoiceninja.com with token TOKEN).
"""

import json
import os
from collections.abc import AsyncIterator

import pytest
from mcp import Client

from invoiceninja_mcp.config import Settings
from invoiceninja_mcp.server import build_server
from tests.conftest import text_of

pytestmark = [
    pytest.mark.live,
    pytest.mark.anyio,
    pytest.mark.skipif(
        not (os.environ.get("INVOICENINJA_URL") and os.environ.get("INVOICENINJA_API_TOKEN")),
        reason="INVOICENINJA_URL / INVOICENINJA_API_TOKEN not set",
    ),
]


@pytest.fixture
async def live() -> AsyncIterator[Client]:
    # never enable writes in smoke tests, whatever the environment says
    settings = Settings.from_env({**os.environ, "INVOICENINJA_ENABLE_WRITES": "false"})
    async with Client(build_server(settings)) as client:
        yield client


async def test_ping(live: Client) -> None:
    result = await live.call_tool("invoiceninja_ping", {})
    assert not result.is_error, text_of(result)
    assert "Connected to Invoice Ninja" in text_of(result)


@pytest.mark.parametrize(
    "tool",
    [
        "invoiceninja_list_clients",
        "invoiceninja_list_invoices",
        "invoiceninja_list_quotes",
        "invoiceninja_list_credits",
        "invoiceninja_list_payments",
        "invoiceninja_list_recurring_invoices",
        "invoiceninja_list_products",
        "invoiceninja_list_expenses",
        "invoiceninja_list_recurring_expenses",
        "invoiceninja_list_vendors",
        "invoiceninja_list_projects",
        "invoiceninja_list_tasks",
        "invoiceninja_list_purchase_orders",
    ],
)
async def test_core_lists(live: Client, tool: str) -> None:
    result = await live.call_tool(tool, {"per_page": 2})
    assert not result.is_error, text_of(result)


async def test_reference_lists(live: Client) -> None:
    for entity in ("tax_rates", "payment_terms", "task_statuses", "activities", "users"):
        result = await live.call_tool("invoiceninja_list_records", {"entity": entity})
        assert not result.is_error, f"{entity}: {text_of(result)}"


async def test_get_first_invoice(live: Client) -> None:
    listing = await live.call_tool(
        "invoiceninja_list_invoices",
        {"per_page": 1, "response_format": "json", "fields": ["number"]},
    )
    data = json.loads(text_of(listing))["data"]
    if not data:
        pytest.skip("instance has no invoices")
    result = await live.call_tool("invoiceninja_get_invoice", {"id": data[0]["id"]})
    assert not result.is_error, text_of(result)


async def test_dashboard_and_statics(live: Client) -> None:
    for tool, args in (
        ("invoiceninja_dashboard_totals", {}),
        ("invoiceninja_get_statics", {"section": "currencies", "search": "usd"}),
        ("invoiceninja_search", {"query": "a"}),
    ):
        result = await live.call_tool(tool, args)
        assert not result.is_error, f"{tool}: {text_of(result)}"


async def test_report(live: Client) -> None:
    result = await live.call_tool(
        "invoiceninja_run_report",
        {"report": "clients", "date_range": "all", "max_wait_seconds": 120, "max_rows": 3},
    )
    assert not result.is_error, text_of(result)
