import json
from typing import get_args

import httpx
import pytest
import respx
from mcp import Client

from invoiceninja_mcp.entities import CORE_ENTITIES
from invoiceninja_mcp.tools.write import CoreEntity
from tests.conftest import text_of

pytestmark = pytest.mark.anyio

WRITE_TOOLS = {
    "invoiceninja_create_record",
    "invoiceninja_update_record",
    "invoiceninja_bulk_action",
}


def test_core_entity_literal_matches_registry() -> None:
    assert set(get_args(CoreEntity)) == set(CORE_ENTITIES)


async def test_write_tools_hidden_by_default(mcp_client: Client) -> None:
    names = {t.name for t in (await mcp_client.list_tools()).tools}
    assert not names & WRITE_TOOLS


async def test_write_tools_visible_when_enabled(mcp_client_rw: Client) -> None:
    tools = {t.name: t for t in (await mcp_client_rw.list_tools()).tools}
    assert set(tools) >= WRITE_TOOLS
    bulk = tools["invoiceninja_bulk_action"].annotations
    assert bulk is not None
    assert bulk.destructive_hint is True
    create = tools["invoiceninja_create_record"].annotations
    assert create is not None
    assert create.read_only_hint is False
    assert create.destructive_hint is False


async def test_create_record(mcp_client_rw: Client, api: respx.MockRouter) -> None:
    created = {"id": "c9", "name": "New Co", "display_name": "New Co", "number": "0042"}
    route = api.post("/clients").mock(return_value=httpx.Response(200, json={"data": created}))
    result = await mcp_client_rw.call_tool(
        "invoiceninja_create_record", {"entity": "clients", "data": {"name": "New Co"}}
    )
    assert not result.is_error, text_of(result)
    assert json.loads(route.calls.last.request.content) == {"name": "New Co"}
    text = text_of(result)
    assert text.startswith("Created client")
    assert "(c9)" in text


async def test_create_requires_data(mcp_client_rw: Client) -> None:
    result = await mcp_client_rw.call_tool(
        "invoiceninja_create_record", {"entity": "clients", "data": {}}
    )
    assert result.is_error


async def test_update_record(mcp_client_rw: Client, api: respx.MockRouter) -> None:
    route = api.put("/invoices/i1").mock(
        return_value=httpx.Response(
            200, json={"data": {"id": "i1", "number": "INV-1", "po_number": "PO-9"}}
        )
    )
    result = await mcp_client_rw.call_tool(
        "invoiceninja_update_record",
        {"entity": "invoices", "id": "i1", "data": {"po_number": "PO-9"}},
    )
    assert not result.is_error, text_of(result)
    assert json.loads(route.calls.last.request.content) == {"po_number": "PO-9"}
    assert text_of(result).startswith("Updated invoice")


async def test_validation_errors_are_reported(mcp_client_rw: Client, api: respx.MockRouter) -> None:
    api.post("/invoices").mock(
        return_value=httpx.Response(
            422,
            json={"message": "invalid", "errors": {"client_id": ["The client id is required."]}},
        )
    )
    result = await mcp_client_rw.call_tool(
        "invoiceninja_create_record", {"entity": "invoices", "data": {"po_number": "x"}}
    )
    assert result.is_error
    assert "client_id: The client id is required." in text_of(result)


async def test_bulk_action(mcp_client_rw: Client, api: respx.MockRouter) -> None:
    route = api.post("/invoices/bulk").mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"id": "i1", "number": "INV-1", "status_id": "4"}]},
        )
    )
    result = await mcp_client_rw.call_tool(
        "invoiceninja_bulk_action",
        {"entity": "invoices", "action": "mark_paid", "ids": ["i1"]},
    )
    assert not result.is_error, text_of(result)
    assert json.loads(route.calls.last.request.content) == {"action": "mark_paid", "ids": ["i1"]}
    text = text_of(result)
    assert "mark_paid" in text
    assert "INV-1 (i1): paid" in text


async def test_bulk_action_passes_extra_fields(
    mcp_client_rw: Client, api: respx.MockRouter
) -> None:
    route = api.post("/invoices/bulk").mock(return_value=httpx.Response(200, json={"data": []}))
    await mcp_client_rw.call_tool(
        "invoiceninja_bulk_action",
        {
            "entity": "invoices",
            "action": "email",
            "ids": ["i1"],
            "extra": {"email_type": "reminder1"},
        },
    )
    body = json.loads(route.calls.last.request.content)
    assert body == {"action": "email", "ids": ["i1"], "email_type": "reminder1"}


async def test_bulk_rejects_action_not_allowed_for_entity(
    mcp_client_rw: Client, api: respx.MockRouter
) -> None:
    route = api.post("/clients/bulk")
    result = await mcp_client_rw.call_tool(
        "invoiceninja_bulk_action", {"entity": "clients", "action": "mark_paid", "ids": ["c1"]}
    )
    assert result.is_error
    assert "archive, restore, delete" in text_of(result)
    assert not route.called


async def test_bulk_requires_ids(mcp_client_rw: Client) -> None:
    result = await mcp_client_rw.call_tool(
        "invoiceninja_bulk_action", {"entity": "invoices", "action": "archive", "ids": []}
    )
    assert result.is_error
