"""Create, update and bulk-action tools. Registered only when INVOICENINJA_ENABLE_WRITES=true."""

from collections.abc import Mapping
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from invoiceninja_mcp.client import InvoiceNinjaClient
from invoiceninja_mcp.entities import CORE_ENTITIES, EntitySpec
from invoiceninja_mcp.formatting import normalize_record, render_record_markdown
from invoiceninja_mcp.tools.common import (
    RecordId,
    annotations,
    data_of,
    record_path,
    tool_errors,
)

CoreEntity = Literal[
    "clients",
    "invoices",
    "quotes",
    "credits",
    "payments",
    "recurring_invoices",
    "products",
    "expenses",
    "recurring_expenses",
    "vendors",
    "projects",
    "tasks",
    "purchase_orders",
]

EntityArg = Annotated[CoreEntity, Field(description="Kind of record")]
Payload = Annotated[
    dict[str, Any],
    Field(description="Fields to send, as accepted by the Invoice Ninja API (see description)"),
]


def _payload_hints() -> str:
    return "\n".join(f"- {spec.path}: {spec.write_hint}" for spec in CORE_ENTITIES.values())


def _actions_doc() -> str:
    return "\n".join(
        f"- {spec.path}: {', '.join(spec.bulk_actions)}" for spec in CORE_ENTITIES.values()
    )


def _state(record: Mapping[str, Any]) -> str:
    if record.get("is_deleted"):
        return "deleted"
    status = record.get("status")
    if record.get("archived_at"):
        return f"{status}, archived" if status else "archived"
    return str(status) if status else "active"


def register(server: MCPServer, client: InvoiceNinjaClient) -> None:
    def require_data(data: Mapping[str, Any]) -> None:
        if not data:
            raise ToolError("data must contain at least one field.")

    def describe(verb: str, spec: EntitySpec, payload: Any) -> str:
        record = normalize_record(spec, data_of(payload) or {})
        singular = spec.singular.replace("_", " ")
        return f"{verb} {singular}.\n\n" + render_record_markdown(spec, record)

    @tool_errors
    async def create_record(entity: EntityArg, data: Payload) -> str:
        require_data(data)
        spec = CORE_ENTITIES[entity]
        return describe("Created", spec, await client.post(f"/{spec.path}", json=data))

    @tool_errors
    async def update_record(entity: EntityArg, id: RecordId, data: Payload) -> str:
        require_data(data)
        spec = CORE_ENTITIES[entity]
        return describe("Updated", spec, await client.put(record_path(spec.path, id), json=data))

    @tool_errors
    async def bulk_action(
        entity: EntityArg,
        action: Annotated[str, Field(min_length=1, description="Action name (see description)")],
        ids: Annotated[
            list[str], Field(min_length=1, max_length=100, description="Hashed ids to act on")
        ],
        extra: Annotated[
            dict[str, Any] | None,
            Field(description="Extra body fields, e.g. {'email_type': 'reminder1'} for email"),
        ] = None,
    ) -> str:
        spec = CORE_ENTITIES[entity]
        if action not in spec.bulk_actions:
            raise ToolError(
                f"Action '{action}' is not supported for {spec.label}. "
                f"Allowed: {', '.join(spec.bulk_actions)}."
            )
        body: dict[str, Any] = {**(extra or {}), "action": action, "ids": ids}
        payload = await client.post(f"/{spec.path}/bulk", json=body)
        records = data_of(payload)
        lines = [f"Applied '{action}' to {len(ids)} {spec.label}."]
        if isinstance(records, list) and records:
            lines.append("Resulting state:")
            for raw in records:
                if not isinstance(raw, Mapping):
                    continue
                rec = normalize_record(spec, raw)
                title = rec.get(spec.title_field) or rec.get("number") or rec.get("name") or ""
                lines.append(f"- {title} ({rec.get('id', '?')}): {_state(rec)}")
        elif isinstance(payload, Mapping) and payload.get("message"):
            lines.append(f"API said: {payload['message']}")
        return "\n".join(lines)

    server.add_tool(
        create_record,
        name="invoiceninja_create_record",
        description=(
            "Create a record in Invoice Ninja. Main fields per entity:\n"
            f"{_payload_hints()}\n"
            "Look up ids (client_id, vendor_id, …) with search/list tools first."
        ),
        annotations=annotations(
            "Create record", read_only_hint=False, destructive_hint=False, idempotent_hint=False
        ),
        structured_output=False,
    )
    server.add_tool(
        update_record,
        name="invoiceninja_update_record",
        description=(
            "Update a record. Send only the fields to change. For line_items send the complete "
            "list: it replaces the existing items. Fields per entity:\n" + _payload_hints()
        ),
        annotations=annotations(
            "Update record", read_only_hint=False, destructive_hint=True, idempotent_hint=True
        ),
        structured_output=False,
    )
    server.add_tool(
        bulk_action,
        name="invoiceninja_bulk_action",
        description=(
            "Run an action on up to 100 records (archive, restore, delete, email, mark as "
            "sent/paid, …). Emails go to real clients and 'delete' cannot be undone from the "
            "API: confirm with the user first. Actions per entity:\n" + _actions_doc()
        ),
        annotations=annotations(
            "Bulk action", read_only_hint=False, destructive_hint=True, idempotent_hint=False
        ),
        structured_output=False,
    )
