import json
from typing import get_args

import httpx
import pytest
import respx
from mcp import Client

from invoiceninja_mcp.entities import CORE_ENTITIES, SECONDARY_ENTITIES
from invoiceninja_mcp.tools.read import SecondaryEntity
from tests.conftest import text_of

pytestmark = pytest.mark.anyio

PAGINATION = {"total": 3, "count": 1, "per_page": 1, "current_page": 1, "total_pages": 3}
INVOICE = {
    "id": "Wpmbk5ezJn",
    "number": "INV-0001",
    "status_id": "4",
    "amount": 100,
    "balance": 0,
    "date": "2026-09-01",
    "due_date": "2026-09-15",
    "client_id": "c1",
    "client": {"id": "c1", "name": "Acme", "contacts": [{"email": "a@acme.test"}]},
    "private_notes": "",
}


async def test_lists_one_list_and_get_tool_per_core_entity(mcp_client: Client) -> None:
    names = {t.name for t in (await mcp_client.list_tools()).tools}
    for spec in CORE_ENTITIES.values():
        assert f"invoiceninja_list_{spec.path}" in names
        assert f"invoiceninja_get_{spec.singular}" in names
    assert {"invoiceninja_list_records", "invoiceninja_get_record"} <= names


async def test_read_tools_are_annotated_read_only(mcp_client: Client) -> None:
    tools = {t.name: t for t in (await mcp_client.list_tools()).tools}
    ann = tools["invoiceninja_list_invoices"].annotations
    assert ann is not None
    assert ann.read_only_hint is True
    assert ann.destructive_hint is False
    assert ann.open_world_hint is True


async def test_list_description_documents_entity_filters(mcp_client: Client) -> None:
    tools = {t.name: t for t in (await mcp_client.list_tools()).tools}
    desc = tools["invoiceninja_list_invoices"].description or ""
    assert "overdue" in desc
    assert "date_range" in desc


def test_secondary_entity_literal_matches_registry() -> None:
    assert set(get_args(SecondaryEntity)) == set(SECONDARY_ENTITIES)


async def test_list_invoices_sends_filters_and_renders_markdown(
    mcp_client: Client, api: respx.MockRouter
) -> None:
    route = api.get("/invoices").mock(
        return_value=httpx.Response(
            200, json={"data": [INVOICE], "meta": {"pagination": PAGINATION}}
        )
    )
    result = await mcp_client.call_tool(
        "invoiceninja_list_invoices",
        {
            "filter": "acme",
            "client_status": "paid",
            "client_id": "c1",
            "sort": "date|desc",
            "page": 1,
            "per_page": 1,
            "extra_filters": {"date_range": "2026-01-01,2026-12-31"},
        },
    )
    assert not result.is_error, text_of(result)
    params = route.calls.last.request.url.params
    assert params["filter"] == "acme"
    assert params["client_status"] == "paid"
    assert params["client_id"] == "c1"
    assert params["sort"] == "date|desc"
    assert params["per_page"] == "1"
    assert params["date_range"] == "2026-01-01,2026-12-31"
    assert params["include"] == "client"
    text = text_of(result)
    assert "| Wpmbk5ezJn | INV-0001 | Acme | paid |" in text
    assert "page=2" in text


async def test_list_merges_user_include_with_name_includes(
    mcp_client: Client, api: respx.MockRouter
) -> None:
    route = api.get("/invoices").mock(return_value=httpx.Response(200, json={"data": []}))
    await mcp_client.call_tool("invoiceninja_list_invoices", {"include": "payments"})
    assert route.calls.last.request.url.params["include"] == "payments,client"


async def test_list_json_format_with_fields(mcp_client: Client, api: respx.MockRouter) -> None:
    api.get("/invoices").mock(
        return_value=httpx.Response(
            200, json={"data": [INVOICE], "meta": {"pagination": PAGINATION}}
        )
    )
    result = await mcp_client.call_tool(
        "invoiceninja_list_invoices",
        {"response_format": "json", "fields": ["number", "client_name", "status"]},
    )
    payload = json.loads(text_of(result))
    assert payload["data"] == [
        {"id": "Wpmbk5ezJn", "number": "INV-0001", "client_name": "Acme", "status": "paid"}
    ]
    assert payload["pagination"]["total"] == 3


async def test_json_without_fields_is_compacted(mcp_client: Client, api: respx.MockRouter) -> None:
    api.get("/invoices").mock(return_value=httpx.Response(200, json={"data": [INVOICE]}))
    result = await mcp_client.call_tool("invoiceninja_list_invoices", {"response_format": "json"})
    record = json.loads(text_of(result))["data"][0]
    assert "private_notes" not in record
    assert "client" not in record
    assert record["balance"] == 0


async def test_per_page_is_bounded(mcp_client: Client) -> None:
    result = await mcp_client.call_tool("invoiceninja_list_invoices", {"per_page": 500})
    assert result.is_error


async def test_get_invoice(mcp_client: Client, api: respx.MockRouter) -> None:
    route = api.get("/invoices/Wpmbk5ezJn").mock(
        return_value=httpx.Response(200, json={"data": INVOICE})
    )
    result = await mcp_client.call_tool("invoiceninja_get_invoice", {"id": "Wpmbk5ezJn"})
    assert not result.is_error, text_of(result)
    assert route.calls.last.request.url.params["include"] == "client"
    assert text_of(result).startswith("# Invoice INV-0001 (Wpmbk5ezJn)")


async def test_get_escapes_id_in_path(mcp_client: Client, api: respx.MockRouter) -> None:
    route = api.get("/clients/a%2Fb").mock(
        return_value=httpx.Response(200, json={"data": {"id": "a/b"}})
    )
    await mcp_client.call_tool("invoiceninja_get_client", {"id": "a/b"})
    assert route.called


async def test_get_not_found_is_actionable_error(mcp_client: Client, api: respx.MockRouter) -> None:
    api.get("/invoices/nope").mock(return_value=httpx.Response(404, json={"message": "nf"}))
    result = await mcp_client.call_tool("invoiceninja_get_invoice", {"id": "nope"})
    assert result.is_error
    assert "list or search" in text_of(result)


async def test_list_records_generic(mcp_client: Client, api: respx.MockRouter) -> None:
    route = api.get("/tax_rates").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "t1", "name": "VAT", "rate": 21}]})
    )
    result = await mcp_client.call_tool("invoiceninja_list_records", {"entity": "tax_rates"})
    assert route.called
    assert "| t1 | VAT | 21 |" in text_of(result)


async def test_list_records_rejects_unknown_entity(mcp_client: Client) -> None:
    result = await mcp_client.call_tool("invoiceninja_list_records", {"entity": "companies"})
    assert result.is_error


async def test_users_never_leak_secrets(mcp_client: Client, api: respx.MockRouter) -> None:
    user = {"id": "u1", "email": "x@y.z", "google_2fa_secret": "SEED", "oauth_user_token": "T"}
    api.get("/users/u1").mock(return_value=httpx.Response(200, json={"data": user}))
    for fmt in ("json", "markdown"):
        result = await mcp_client.call_tool(
            "invoiceninja_get_record", {"entity": "users", "id": "u1", "response_format": fmt}
        )
        assert "SEED" not in text_of(result)
        assert "oauth_user_token" not in text_of(result)


async def test_empty_json_list_keeps_data_key(mcp_client: Client, api: respx.MockRouter) -> None:
    api.get("/credits").mock(return_value=httpx.Response(200, json={"data": []}))
    result = await mcp_client.call_tool("invoiceninja_list_credits", {"response_format": "json"})
    assert json.loads(text_of(result))["data"] == []


async def test_json_list_omits_bulky_fields_by_default(
    mcp_client: Client, api: respx.MockRouter
) -> None:
    record = {**INVOICE, "invitations": [{"key": "k"}], "backup": {"x": 1}, "settings": {"a": 1}}
    api.get("/invoices").mock(return_value=httpx.Response(200, json={"data": [record]}))
    result = await mcp_client.call_tool("invoiceninja_list_invoices", {"response_format": "json"})
    payload = json.loads(text_of(result))
    assert "invitations" not in payload["data"][0]
    assert "backup" not in payload["data"][0]
    assert "invitations" in payload["omitted_fields"]


async def test_json_list_fields_can_request_bulky_fields(
    mcp_client: Client, api: respx.MockRouter
) -> None:
    record = {**INVOICE, "invitations": [{"key": "k"}]}
    api.get("/invoices").mock(return_value=httpx.Response(200, json={"data": [record]}))
    result = await mcp_client.call_tool(
        "invoiceninja_list_invoices", {"response_format": "json", "fields": ["invitations"]}
    )
    assert json.loads(text_of(result))["data"][0]["invitations"] == [{"key": "k"}]


async def test_oversized_json_list_drops_records_and_stays_valid(
    mcp_client: Client, api: respx.MockRouter
) -> None:
    records = [{**INVOICE, "id": f"i{n}", "public_notes": "x" * 4000} for n in range(20)]
    api.get("/invoices").mock(return_value=httpx.Response(200, json={"data": records}))
    result = await mcp_client.call_tool("invoiceninja_list_invoices", {"response_format": "json"})
    text = text_of(result)
    payload = json.loads(text)
    assert len(text) <= 25_000
    assert 0 < len(payload["data"]) < 20
    assert payload["truncated"]["returned"] == len(payload["data"])
    assert payload["truncated"]["fetched"] == 20
