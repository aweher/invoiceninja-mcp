import base64
import json

import httpx
import pytest
import respx
from mcp import Client

from tests.conftest import text_of

pytestmark = pytest.mark.anyio

SEARCH_PAYLOAD = {
    "clients": [
        {"name": "Acme Corp", "type": "/client", "id": "c1", "path": "/clients/c1"},
        {"name": "Globex", "type": "/client", "id": "c2", "path": "/clients/c2"},
    ],
    "client_contacts": [
        {"name": "Jane Doe <jane@acme.test>", "type": "/client", "id": "c1", "path": "/clients/c1"}
    ],
    "invoices": [
        {"name": "Acme Corp - INV-7", "type": "/invoice", "id": "i7", "path": "/invoices/i7/edit"}
    ],
    "projects": [],
    "settings": [{"name": "Accent Color", "id": "/settings/x"}],
}

REPORT_JSON = {
    "columns": [
        {"identifier": "client.name", "display_value": "Name"},
        {"identifier": "client.balance", "display_value": "Balance"},
    ],
    "0": [
        {"identifier": "client.name", "display_value": "Acme"},
        {"identifier": "client.balance", "display_value": "10.00"},
    ],
    "1": [
        {"identifier": "client.name", "display_value": "Globex"},
        {"identifier": "client.balance", "display_value": "5.00"},
    ],
}


async def test_ping(mcp_client: Client, api: respx.MockRouter) -> None:
    api.get("/ping").mock(
        return_value=httpx.Response(200, json={"company_name": "Acme", "user_name": "Ariel"})
    )
    result = await mcp_client.call_tool("invoiceninja_ping", {})
    assert not result.is_error
    assert "Acme" in text_of(result)
    assert "Ariel" in text_of(result)


async def test_search_filters_locally_and_drops_settings(
    mcp_client: Client, api: respx.MockRouter
) -> None:
    route = api.post("/search").mock(return_value=httpx.Response(200, json=SEARCH_PAYLOAD))
    result = await mcp_client.call_tool("invoiceninja_search", {"query": "acme"})
    assert json.loads(route.calls.last.request.content) == {"search": "acme"}
    text = text_of(result)
    assert "Acme Corp (c1)" in text
    assert "Acme Corp - INV-7 (i7)" in text
    assert "jane@acme.test" in text
    assert "Globex" not in text
    assert "Accent Color" not in text


async def test_search_matches_all_words(mcp_client: Client, api: respx.MockRouter) -> None:
    api.post("/search").mock(return_value=httpx.Response(200, json=SEARCH_PAYLOAD))
    result = await mcp_client.call_tool("invoiceninja_search", {"query": "acme inv-7"})
    text = text_of(result)
    assert "INV-7" in text
    assert "Acme Corp (c1)" not in text


async def test_search_no_results(mcp_client: Client, api: respx.MockRouter) -> None:
    api.post("/search").mock(return_value=httpx.Response(200, json=SEARCH_PAYLOAD))
    result = await mcp_client.call_tool("invoiceninja_search", {"query": "zzz"})
    assert "No matches" in text_of(result)


async def test_statics_section_with_search(mcp_client: Client, api: respx.MockRouter) -> None:
    statics = {
        "currencies": [
            {"id": "1", "name": "US Dollar", "code": "USD"},
            {"id": "3", "name": "Euro", "code": "EUR"},
        ],
        "templates": {"invoice": {}},
    }
    api.get("/statics").mock(return_value=httpx.Response(200, json=statics))
    result = await mcp_client.call_tool(
        "invoiceninja_get_statics", {"section": "currencies", "search": "eur"}
    )
    data = json.loads(text_of(result))
    assert data == {"currencies": [{"id": "3", "name": "Euro", "code": "EUR"}], "total": 1}


async def test_dashboard_totals(mcp_client: Client, api: respx.MockRouter) -> None:
    payload = {
        "currencies": {"1": "USD"},
        "start_date": "2026-01-01",
        "end_date": "2026-12-31",
        "1": {
            "invoices": {"invoiced_amount": "100.00", "code": "USD"},
            "revenue": {"paid_to_date": "60.00", "code": "USD"},
            "outstanding": {"amount": "40.00", "outstanding_count": 2, "code": "USD"},
            "expenses": {"amount": "15.00", "code": "USD"},
        },
    }
    route = api.post("/charts/totals").mock(return_value=httpx.Response(200, json=payload))
    result = await mcp_client.call_tool(
        "invoiceninja_dashboard_totals", {"start_date": "2026-01-01", "end_date": "2026-12-31"}
    )
    assert json.loads(route.calls.last.request.content) == {
        "start_date": "2026-01-01",
        "end_date": "2026-12-31",
    }
    text = text_of(result)
    assert "| USD | 100.00 | 60.00 | 40.00 (2) | 15.00 |" in text


async def test_run_report_polls_until_ready(mcp_client: Client, api: respx.MockRouter) -> None:
    start = api.post("/reports/clients").mock(
        return_value=httpx.Response(200, json={"message": "hash-1"})
    )
    preview = api.post("/reports/preview/hash-1").mock(
        side_effect=[
            httpx.Response(409, json={"message": "Still working....."}),
            httpx.Response(409, json={"message": "Still working....."}),
            httpx.Response(200, json=REPORT_JSON),
        ]
    )
    result = await mcp_client.call_tool(
        "invoiceninja_run_report", {"report": "clients", "date_range": "this_year"}
    )
    assert not result.is_error, text_of(result)
    body = json.loads(start.calls.last.request.content)
    assert body == {
        "date_range": "this_year",
        "report_keys": [],
        "send_email": False,
        "include_deleted": False,
        "output": "json",
    }
    assert preview.call_count == 3
    text = text_of(result)
    assert "| Name | Balance |" in text
    assert "| Acme | 10.00 |" in text
    assert "client.balance" in text


async def test_run_report_json_and_max_rows(mcp_client: Client, api: respx.MockRouter) -> None:
    api.post("/reports/clients").mock(return_value=httpx.Response(200, json={"message": "h"}))
    api.post("/reports/preview/h").mock(return_value=httpx.Response(200, json=REPORT_JSON))
    result = await mcp_client.call_tool(
        "invoiceninja_run_report",
        {"report": "clients", "date_range": "all", "max_rows": 1, "response_format": "json"},
    )
    data = json.loads(text_of(result))
    assert data["total_rows"] == 2
    assert data["rows"] == [{"Name": "Acme", "Balance": "10.00"}]
    assert data["truncated"] is True


async def test_run_report_returns_report_id_when_not_ready(
    mcp_client: Client, api: respx.MockRouter
) -> None:
    api.post("/reports/invoices").mock(return_value=httpx.Response(200, json={"message": "h2"}))
    api.post("/reports/preview/h2").mock(
        return_value=httpx.Response(409, json={"message": "Still working....."})
    )
    result = await mcp_client.call_tool(
        "invoiceninja_run_report",
        {"report": "invoices", "date_range": "all", "max_wait_seconds": 0},
    )
    assert not result.is_error
    text = text_of(result)
    assert "h2" in text
    assert "invoiceninja_get_report_result" in text


async def test_get_report_result(mcp_client: Client, api: respx.MockRouter) -> None:
    api.post("/reports/preview/h3").mock(return_value=httpx.Response(200, json=REPORT_JSON))
    result = await mcp_client.call_tool("invoiceninja_get_report_result", {"report_id": "h3"})
    assert "| Globex | 5.00 |" in text_of(result)


async def test_csv_report_is_decoded(mcp_client: Client, api: respx.MockRouter) -> None:
    csv_text = "Type,Amount\nIncome,100\nExpenses,40\n"
    encoded = base64.b64encode(csv_text.encode()).decode()
    start = api.post("/reports/profitloss").mock(
        return_value=httpx.Response(200, json={"message": "h4"})
    )
    api.post("/reports/preview/h4").mock(return_value=httpx.Response(200, json=encoded))
    result = await mcp_client.call_tool(
        "invoiceninja_run_report", {"report": "profitloss", "date_range": "last_year"}
    )
    body = json.loads(start.calls.last.request.content)
    assert body["is_income_billed"] is True
    assert body["include_tax"] is False
    assert "| Income | 100 |" in text_of(result)


async def test_custom_range_requires_dates(mcp_client: Client) -> None:
    result = await mcp_client.call_tool(
        "invoiceninja_run_report", {"report": "clients", "date_range": "custom"}
    )
    assert result.is_error
    assert "start_date" in text_of(result)


async def test_custom_range_sends_dates(mcp_client: Client, api: respx.MockRouter) -> None:
    start = api.post("/reports/payments").mock(
        return_value=httpx.Response(200, json={"message": "h5"})
    )
    api.post("/reports/preview/h5").mock(return_value=httpx.Response(200, json=REPORT_JSON))
    await mcp_client.call_tool(
        "invoiceninja_run_report",
        {
            "report": "payments",
            "date_range": "custom",
            "start_date": "2026-01-01",
            "end_date": "2026-03-31",
            "report_keys": ["payment.date", "payment.amount"],
            "client_id": "c1",
        },
    )
    body = json.loads(start.calls.last.request.content)
    assert body["start_date"] == "2026-01-01"
    assert body["end_date"] == "2026-03-31"
    assert body["report_keys"] == ["payment.date", "payment.amount"]
    assert body["client_id"] == "c1"
