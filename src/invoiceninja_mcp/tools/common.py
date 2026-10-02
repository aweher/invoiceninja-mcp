"""Helpers shared by every tool module."""

import json
from collections.abc import Awaitable, Callable, Mapping
from functools import wraps
from typing import Annotated, Any, Literal
from urllib.parse import quote

from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from invoiceninja_mcp.client import InvoiceNinjaError
from invoiceninja_mcp.formatting import truncate

ResponseFormat = Annotated[
    Literal["markdown", "json"],
    Field(
        description=(
            "'markdown' (default) for a readable summary, 'json' for complete machine-readable "
            "data (empty fields removed)"
        )
    ),
]
Fields = Annotated[
    list[str] | None,
    Field(
        description=(
            "JSON format only: return just these top-level fields (id is always included), "
            "e.g. ['number', 'client_name', 'balance', 'due_date']"
        )
    ),
]
RecordId = Annotated[
    str,
    Field(min_length=1, max_length=64, description="Hashed record id, e.g. 'Opnel5aKBz'"),
]

READ_ONLY = {"read_only_hint": True, "destructive_hint": False, "idempotent_hint": True}


def annotations(title: str, **hints: bool) -> ToolAnnotations:
    return ToolAnnotations(title=title, open_world_hint=True, **hints)


def tool_errors[**P](fn: Callable[P, Awaitable[str]]) -> Callable[P, Awaitable[str]]:
    """Turn API errors into MCP tool errors and keep responses within the size budget."""

    @wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> str:
        try:
            return truncate(await fn(*args, **kwargs))
        except InvoiceNinjaError as exc:
            raise ToolError(str(exc)) from None

    return wrapper


def to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1, default=str)


def record_path(path: str, record_id: str) -> str:
    return f"/{path}/{quote(record_id, safe='')}"


def data_of(payload: Any) -> Any:
    if isinstance(payload, Mapping) and "data" in payload:
        return payload["data"]
    return payload
