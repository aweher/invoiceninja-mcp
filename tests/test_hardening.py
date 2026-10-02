"""Regression tests for the issues found in the independent code review."""

import base64
import json

import httpx
import pytest
import respx
from mcp import Client

from invoiceninja_mcp.client import InvoiceNinjaClient, InvoiceNinjaError
from invoiceninja_mcp.formatting import redact
from tests.conftest import API, make_settings, text_of

pytestmark = pytest.mark.anyio

REPORT_JSON = {
    "columns": [{"identifier": "client.name", "display_value": "Name"}],
    "0": [{"identifier": "client.name", "display_value": "Acme"}],
}


# --- path traversal through ids -------------------------------------------------


@pytest.mark.parametrize("report_id", ["../../clients", "../../invoices/bulk?x=1", "a/b", ".."])
async def test_report_id_cannot_escape_preview_path(
    mcp_client: Client, api: respx.MockRouter, report_id: str
) -> None:
    catch_all = api.route().respond(200, json={"data": {}})
    result = await mcp_client.call_tool(
        "invoiceninja_get_report_result", {"report_id": report_id, "max_wait_seconds": 0}
    )
    assert result.is_error
    assert not catch_all.called


@pytest.mark.parametrize("record_id", ["..", ".", "a/b", "../clients"])
async def test_record_id_rejects_path_segments(
    mcp_client: Client, api: respx.MockRouter, record_id: str
) -> None:
    catch_all = api.route().respond(200, json={"data": {"id": "x"}})
    result = await mcp_client.call_tool("invoiceninja_get_invoice", {"id": record_id})
    assert result.is_error
    assert not catch_all.called


async def test_run_report_rejects_weird_report_id(
    mcp_client: Client, api: respx.MockRouter
) -> None:
    api.post("/reports/clients").mock(
        return_value=httpx.Response(200, json={"message": "../../logout"})
    )
    preview = api.route().respond(200, json=REPORT_JSON)
    result = await mcp_client.call_tool(
        "invoiceninja_run_report", {"report": "clients", "date_range": "all"}
    )
    assert result.is_error
    assert not preview.called


# --- CSV reports with a title row ----------------------------------------------------


async def test_profit_and_loss_csv_keeps_all_columns(
    mcp_client: Client, api: respx.MockRouter
) -> None:
    csv_text = (
        '"Profit and Loss"\n'
        '"Total Revenue[Tax Exclusive]","$24,078.00"\n'
        '"Total Profit","$20,000.00"\n'
    )
    api.post("/reports/profitloss").mock(return_value=httpx.Response(200, json={"message": "p1"}))
    api.post("/reports/preview/p1").mock(
        return_value=httpx.Response(200, json=base64.b64encode(csv_text.encode()).decode())
    )
    result = await mcp_client.call_tool(
        "invoiceninja_run_report", {"report": "profitloss", "date_range": "this_year"}
    )
    text = text_of(result)
    assert "$24,078.00" in text
    assert "$20,000.00" in text
    assert "Profit and Loss" in text


# --- redaction of bearer links ------------------------------------------------------


def test_redact_removes_portal_and_payment_links() -> None:
    record = {
        "client_hash": "h",
        "contacts": [
            {"email": "a@b.c", "contact_key": "ck", "link": "https://x/client/key_login/ck"}
        ],
        "invitations": [
            {"id": "i", "key": "k", "link": "https://x/client/invoice/k", "sent_date": "d"}
        ],
        "webhook_configuration": {"post_purchase_headers": {"Authorization": "Bearer z"}},
    }
    assert redact(record) == {
        "contacts": [{"email": "a@b.c"}],
        "invitations": [{"id": "i", "sent_date": "d"}],
        "webhook_configuration": {},
    }


async def test_dashboard_and_reports_are_redacted(
    mcp_client: Client, api: respx.MockRouter
) -> None:
    api.post("/charts/totals").mock(
        return_value=httpx.Response(200, json={"currencies": {}, "password": "p"})
    )
    result = await mcp_client.call_tool(
        "invoiceninja_dashboard_totals", {"response_format": "json"}
    )
    assert "password" not in text_of(result)


# --- report id lifecycle --------------------------------------------------------------


async def test_unknown_report_id_is_an_error(mcp_client: Client, api: respx.MockRouter) -> None:
    preview = api.post("/reports/preview/nope123")
    result = await mcp_client.call_tool(
        "invoiceninja_get_report_result", {"report_id": "nope123", "max_wait_seconds": 0}
    )
    assert result.is_error
    assert "run_report" in text_of(result)
    assert not preview.called


async def test_finished_report_can_be_read_again(mcp_client: Client, api: respx.MockRouter) -> None:
    api.post("/reports/clients").mock(return_value=httpx.Response(200, json={"message": "r-1"}))
    preview = api.post("/reports/preview/r-1").mock(
        return_value=httpx.Response(200, json=REPORT_JSON)
    )
    await mcp_client.call_tool(
        "invoiceninja_run_report", {"report": "clients", "date_range": "all"}
    )
    again = await mcp_client.call_tool("invoiceninja_get_report_result", {"report_id": "r-1"})
    assert not again.is_error, text_of(again)
    assert "| Acme |" in text_of(again)
    assert preview.call_count == 1


async def test_pending_report_then_result(mcp_client: Client, api: respx.MockRouter) -> None:
    api.post("/reports/quotes").mock(return_value=httpx.Response(200, json={"message": "q-1"}))
    api.post("/reports/preview/q-1").mock(
        side_effect=[httpx.Response(409, json={}), httpx.Response(200, json=REPORT_JSON)]
    )
    first = await mcp_client.call_tool(
        "invoiceninja_run_report",
        {"report": "quotes", "date_range": "all", "max_wait_seconds": 0},
    )
    assert "q-1" in text_of(first)
    second = await mcp_client.call_tool("invoiceninja_get_report_result", {"report_id": "q-1"})
    assert "| Acme |" in text_of(second)


# --- non-dict payloads ----------------------------------------------------------------


async def test_non_dict_payload_gives_clear_error(
    mcp_client: Client, api: respx.MockRouter
) -> None:
    api.get("/ping").mock(return_value=httpx.Response(200, json=["unexpected"]))
    result = await mcp_client.call_tool("invoiceninja_ping", {})
    assert result.is_error
    assert "unexpected" in text_of(result).lower()


async def test_get_with_non_dict_data(mcp_client: Client, api: respx.MockRouter) -> None:
    api.get("/invoices/abc").mock(return_value=httpx.Response(200, json={"data": [1, 2]}))
    result = await mcp_client.call_tool("invoiceninja_get_invoice", {"id": "abc"})
    assert result.is_error
    assert "unexpected" in text_of(result).lower()


# --- token scrubbing in error text ---------------------------------------------------


async def test_error_text_never_echoes_token() -> None:
    settings = make_settings()
    async with InvoiceNinjaClient(settings) as client:
        with respx.mock:
            respx.get(f"{API}/ping").mock(
                return_value=httpx.Response(500, text="debug: X-API-TOKEN=tok-123")
            )
            with pytest.raises(InvoiceNinjaError) as exc:
                await client.get("/ping")
    assert "tok-123" not in str(exc.value)


# --- schemas only expose filters the entity supports --------------------------------


async def test_list_schemas_match_entity_filters(mcp_client: Client) -> None:
    tools = {t.name: t.input_schema["properties"] for t in (await mcp_client.list_tools()).tools}
    assert "client_id" not in tools["invoiceninja_list_clients"]
    assert "client_status" not in tools["invoiceninja_list_clients"]
    assert "client_status" not in tools["invoiceninja_list_products"]
    assert "client_id" not in tools["invoiceninja_list_purchase_orders"]
    assert "client_status" in tools["invoiceninja_list_purchase_orders"]
    assert {"client_id", "client_status"} <= set(tools["invoiceninja_list_invoices"])
    assert "client_id" in tools["invoiceninja_list_projects"]


async def test_extra_filters_are_not_overwritten_by_unset_params(
    mcp_client: Client, api: respx.MockRouter
) -> None:
    route = api.get("/invoices").mock(return_value=httpx.Response(200, json={"data": []}))
    await mcp_client.call_tool(
        "invoiceninja_list_invoices", {"extra_filters": {"status": "archived", "sort": "id|asc"}}
    )
    params = route.calls.last.request.url.params
    assert params["status"] == "archived"
    assert params["sort"] == "id|asc"


# --- dashboard -----------------------------------------------------------------------


async def test_dashboard_requires_both_dates(mcp_client: Client, api: respx.MockRouter) -> None:
    result = await mcp_client.call_tool(
        "invoiceninja_dashboard_totals", {"start_date": "2026-01-01"}
    )
    assert result.is_error
    assert not api.calls


async def test_dashboard_shows_combined_totals(mcp_client: Client, api: respx.MockRouter) -> None:
    payload = {
        "currencies": {"1": "USD"},
        "1": {"invoices": {"invoiced_amount": "10"}},
        "999": {"invoices": {"invoiced_amount": "12"}, "revenue": {"paid_to_date": "5"}},
    }
    api.post("/charts/totals").mock(return_value=httpx.Response(200, json=payload))
    result = await mcp_client.call_tool("invoiceninja_dashboard_totals", {})
    assert "| All (company currency) | 12.00 | 5.00 |" in text_of(result)


# --- search fallback -----------------------------------------------------------------


async def test_search_falls_back_to_list_filters(mcp_client: Client, api: respx.MockRouter) -> None:
    api.post("/search").mock(return_value=httpx.Response(200, json={"clients": []}))
    clients = api.get("/clients").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "c7", "display_name": "Old Co"}]})
    )
    api.get("/invoices").mock(
        return_value=httpx.Response(
            200, json={"data": [{"id": "i9", "number": "0009", "client": {"name": "Old Co"}}]}
        )
    )
    result = await mcp_client.call_tool("invoiceninja_search", {"query": "old co"})
    assert clients.calls.last.request.url.params["filter"] == "old co"
    text = text_of(result)
    assert "Old Co (c7)" in text
    assert "0009" in text
    assert json.loads(json.dumps(text))  # plain text, no crash
