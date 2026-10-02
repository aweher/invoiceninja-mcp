"""List/get tools generated from the entity registry."""

import inspect
from collections.abc import Awaitable, Callable, Mapping
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from pydantic import Field

from invoiceninja_mcp.client import InvoiceNinjaClient
from invoiceninja_mcp.entities import (
    COMMON_FILTERS_DOC,
    CORE_ENTITIES,
    SECONDARY_ENTITIES,
    EntitySpec,
)
from invoiceninja_mcp.formatting import (
    CHARACTER_LIMIT,
    compact,
    normalize_record,
    project,
    render_list_markdown,
    render_record_markdown,
)
from invoiceninja_mcp.tools.common import (
    READ_ONLY,
    Fields,
    RecordId,
    ResponseFormat,
    annotations,
    data_of,
    expect_dict,
    record_path,
    to_json,
    tool_errors,
)

SecondaryEntity = Literal[
    "tax_rates",
    "payment_terms",
    "expense_categories",
    "task_statuses",
    "group_settings",
    "designs",
    "documents",
    "bank_transactions",
    "activities",
    "tags",
    "locations",
    "subscriptions",
    "recurring_quotes",
    "users",
]

# Large nested/text fields left out of JSON listings unless asked for via `fields`.
LIST_JSON_BULKY = frozenset(
    {"invitations", "documents", "backup", "settings", "e_invoice", "tax_info", "footer"}
)
JSON_BUDGET = CHARACTER_LIMIT - 500

Filter = Annotated[
    str | None,
    Field(description="Free-text search across the main columns (number, name, contacts, notes…)"),
]
ClientId = Annotated[str | None, Field(description="Only records of this client (hashed id)")]
Status = Annotated[
    str | None,
    Field(
        description=(
            "Lifecycle filter, comma separated: active, archived, deleted "
            "(e.g. 'active' to skip archived and deleted records)"
        )
    ),
]
Sort = Annotated[
    str | None, Field(description="Sort as 'column|asc' or 'column|desc', e.g. 'date|desc'")
]
Page = Annotated[int, Field(ge=1, description="Page number, starting at 1")]
PerPage = Annotated[int, Field(ge=1, le=100, description="Records per page (1-100)")]
Include = Annotated[
    str | None,
    Field(description="Extra relations to embed, comma separated (e.g. 'payments,activities')"),
]
ExtraFilters = Annotated[
    dict[str, str] | None,
    Field(description="Additional API query filters as name -> value (see the tool description)"),
]


def _include_param(spec: EntitySpec, include: str | None) -> str | None:
    parts = [p.strip() for p in (include or "").split(",") if p.strip()]
    parts += [rel for rel in spec.name_includes if rel not in parts]
    return ",".join(parts) or None


def _user_includes(include: str | None) -> tuple[str, ...]:
    return tuple(p.strip() for p in (include or "").split(",") if p.strip())


async def list_entity(
    client: InvoiceNinjaClient,
    spec: EntitySpec,
    *,
    filter: str | None = None,
    client_status: str | None = None,
    client_id: str | None = None,
    status: str | None = None,
    sort: str | None = None,
    page: int = 1,
    per_page: int = 20,
    include: str | None = None,
    extra_filters: Mapping[str, str] | None = None,
    fields: list[str] | None = None,
    response_format: str = "markdown",
) -> str:
    params: dict[str, Any] = dict(extra_filters or {})
    explicit = {
        "filter": filter,
        "client_status": client_status,
        "client_id": client_id,
        "status": status,
        "sort": sort,
        "page": page,
        "per_page": per_page,
    }
    params.update({k: v for k, v in explicit.items() if v is not None})
    params["include"] = _include_param(spec, include or params.get("include"))
    payload = expect_dict(await client.get(f"/{spec.path}", params=params), spec.label)
    keep = _user_includes(include)
    rows = data_of(payload) or []
    if not isinstance(rows, list):
        rows = []
    records = [normalize_record(spec, r, keep) for r in rows if isinstance(r, Mapping)]
    meta = payload.get("meta")
    pagination = (meta if isinstance(meta, Mapping) else {}).get("pagination") or {}
    if response_format == "json":
        return _list_json(records, pagination, fields)
    return render_list_markdown(spec, records, pagination)


def _list_json(
    records: list[dict[str, Any]], pagination: Mapping[str, Any], fields: list[str] | None
) -> str:
    """JSON listing that always parses: bulky fields are opt-in and records (never characters)
    are dropped to stay within the response budget."""
    omitted: set[str] = set()
    data: list[Any] = []
    for record in records:
        if fields:
            data.append(compact(project(record, fields)))
            continue
        omitted |= LIST_JSON_BULKY & record.keys()
        data.append(compact({k: v for k, v in record.items() if k not in LIST_JSON_BULKY}))
    result: dict[str, Any] = {
        "data": data,
        "pagination": {k: v for k, v in pagination.items() if k != "links"},
    }
    if omitted:
        result["omitted_fields"] = sorted(omitted)
        result["note"] = (
            "Bulky fields are omitted from listings; request them with 'fields' "
            "or use the get tool for the full record."
        )
    text = to_json(result)
    fetched = len(data)
    while len(text) > JSON_BUDGET and len(data) > 1:
        data.pop()
        result["truncated"] = {
            "returned": len(data),
            "fetched": fetched,
            "note": "Response too large; use a smaller per_page, 'fields', or the next page.",
        }
        text = to_json(result)
    return text


async def get_entity(
    client: InvoiceNinjaClient,
    spec: EntitySpec,
    record_id: str,
    *,
    include: str | None = None,
    fields: list[str] | None = None,
    response_format: str = "markdown",
) -> str:
    payload = await client.get(
        record_path(spec.path, record_id), params={"include": _include_param(spec, include)}
    )
    data = data_of(expect_dict(payload, spec.singular))
    record = normalize_record(
        spec, expect_dict(data, spec.singular.replace("_", " ")), _user_includes(include)
    )
    if response_format == "json":
        return to_json(compact({"data": project(record, fields) if fields else record}))
    return render_record_markdown(spec, record)


def _list_description(spec: EntitySpec) -> str:
    lines = [f"List {spec.label} from Invoice Ninja with filtering, sorting and pagination."]
    if spec.client_status_values:
        lines.append(f"client_status values: {', '.join(spec.client_status_values)}.")
    if spec.extra_filters:
        lines.append(f"extra_filters keys: {spec.extra_filters}; {COMMON_FILTERS_DOC}.")
    else:
        lines.append(f"extra_filters keys: {COMMON_FILTERS_DOC}.")
    if spec.name_includes:
        names = ", ".join(f"{r}_name" for r in spec.name_includes)
        lines.append(f"Related names are resolved automatically ({names}).")
    lines.append(
        f"Use invoiceninja_get_{spec.singular} with an id from this list for the full record."
    )
    return "\n".join(lines)


def _list_parameters(spec: EntitySpec) -> list[inspect.Parameter]:
    def param(name: str, annotation: Any, default: Any) -> inspect.Parameter:
        return inspect.Parameter(
            name, inspect.Parameter.KEYWORD_ONLY, default=default, annotation=annotation
        )

    params = [param("filter", Filter, None)]
    if spec.client_status_values:
        values = ", ".join(spec.client_status_values)
        client_status = Annotated[
            str | None,
            Field(description=f"Business status filter, comma separated; one or more of: {values}"),
        ]
        params.append(param("client_status", client_status, None))
    if spec.has_client_filter:
        params.append(param("client_id", ClientId, None))
    params += [
        param("status", Status, None),
        param("sort", Sort, None),
        param("page", Page, 1),
        param("per_page", PerPage, 20),
        param("include", Include, None),
        param("extra_filters", ExtraFilters, None),
        param("fields", Fields, None),
        param("response_format", ResponseFormat, "markdown"),
    ]
    return params


def _make_list_tool(client: InvoiceNinjaClient, spec: EntitySpec) -> Callable[..., Awaitable[str]]:
    """Build a list tool whose schema only exposes the filters this entity supports."""

    async def list_tool(**kwargs: Any) -> str:
        return await list_entity(client, spec, **kwargs)

    tool = tool_errors(list_tool)
    # the MCP SDK derives the input schema from inspect.signature(), which honours this
    setattr(tool, "__signature__", inspect.Signature(_list_parameters(spec), return_annotation=str))  # noqa: B010
    return tool


def _make_get_tool(client: InvoiceNinjaClient, spec: EntitySpec) -> Callable[..., Awaitable[str]]:
    @tool_errors
    async def get_tool(
        id: RecordId,
        include: Include = None,
        fields: Fields = None,
        response_format: ResponseFormat = "markdown",
    ) -> str:
        return await get_entity(
            client, spec, id, include=include, fields=fields, response_format=response_format
        )

    return get_tool


def register(server: MCPServer, client: InvoiceNinjaClient) -> None:
    for spec in CORE_ENTITIES.values():
        server.add_tool(
            _make_list_tool(client, spec),
            name=f"invoiceninja_list_{spec.path}",
            description=_list_description(spec),
            annotations=annotations(f"List {spec.label}", **READ_ONLY),
            structured_output=False,
        )
        server.add_tool(
            _make_get_tool(client, spec),
            name=f"invoiceninja_get_{spec.singular}",
            description=(
                f"Get one {spec.singular.replace('_', ' ')} by its hashed id, with all details"
                + (" (line items included)" if "line_items" in spec.write_hint else "")
                + "."
            ),
            annotations=annotations(f"Get {spec.singular.replace('_', ' ')}", **READ_ONLY),
            structured_output=False,
        )

    secondary = ", ".join(SECONDARY_ENTITIES)

    @tool_errors
    async def list_records(
        entity: Annotated[SecondaryEntity, Field(description="Which kind of record to list")],
        filter: Filter = None,
        status: Status = None,
        sort: Sort = None,
        page: Page = 1,
        per_page: PerPage = 20,
        extra_filters: ExtraFilters = None,
        fields: Fields = None,
        response_format: ResponseFormat = "markdown",
    ) -> str:
        return await list_entity(
            client,
            SECONDARY_ENTITIES[entity],
            filter=filter,
            status=status,
            sort=sort,
            page=page,
            per_page=per_page,
            extra_filters=extra_filters,
            fields=fields,
            response_format=response_format,
        )

    @tool_errors
    async def get_record(
        entity: Annotated[SecondaryEntity, Field(description="Which kind of record to fetch")],
        id: RecordId,
        fields: Fields = None,
        response_format: ResponseFormat = "markdown",
    ) -> str:
        return await get_entity(
            client,
            SECONDARY_ENTITIES[entity],
            id,
            fields=fields,
            response_format=response_format,
        )

    server.add_tool(
        list_records,
        name="invoiceninja_list_records",
        description=(
            "List reference/secondary records: "
            f"{secondary}. Use it to resolve ids found on other records "
            "(e.g. category_id, status ids, tax names) or to browse the activity log."
        ),
        annotations=annotations("List reference records", **READ_ONLY),
        structured_output=False,
    )
    server.add_tool(
        get_record,
        name="invoiceninja_get_record",
        description=f"Get one reference/secondary record by id. Entities: {secondary}.",
        annotations=annotations("Get reference record", **READ_ONLY),
        structured_output=False,
    )
