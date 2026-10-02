"""Connection check, lookups, search, dashboard totals and reports."""

import base64
import binascii
import csv
import io
import time
from collections.abc import Mapping
from typing import Annotated, Any, Literal

import anyio
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from invoiceninja_mcp.client import InvoiceNinjaClient, InvoiceNinjaError
from invoiceninja_mcp.formatting import compact, markdown_table, md_cell
from invoiceninja_mcp.tools.common import (
    READ_ONLY,
    ResponseFormat,
    annotations,
    to_json,
    tool_errors,
)

ReportType = Literal[
    "activities",
    "ar_detail_report",
    "ar_summary_report",
    "client_balance_report",
    "client_contacts",
    "client_sales_report",
    "clients",
    "credits",
    "documents",
    "expenses",
    "invoice_items",
    "invoices",
    "payments",
    "product_sales",
    "products",
    "profitloss",
    "projects",
    "purchase_order_items",
    "purchase_orders",
    "quote_items",
    "quotes",
    "recurring_invoice_items",
    "recurring_invoices",
    "tasks",
    "tax_period_report",
    "tax_summary_report",
    "user_sales_report",
    "vendors",
]
DateRange = Literal[
    "all",
    "last7_days",
    "last30_days",
    "last365_days",
    "this_month",
    "last_month",
    "this_quarter",
    "last_quarter",
    "this_year",
    "last_year",
    "custom",
]
StaticsSection = Literal[
    "currencies",
    "countries",
    "payment_types",
    "languages",
    "timezones",
    "industries",
    "sizes",
    "date_formats",
    "datetime_formats",
    "gateways",
]
IsoDate = Annotated[
    str | None,
    Field(pattern=r"^\d{4}-\d{2}-\d{2}$", description="Date as YYYY-MM-DD"),
]
MaxWait = Annotated[
    int,
    Field(ge=0, le=300, description="Seconds to wait for the report before returning its id"),
]
MaxRows = Annotated[int, Field(ge=1, le=1000, description="Maximum rows to return")]

_SEARCH_GROUPS = {
    "clients": "Clients",
    "client_contacts": "Client contacts",
    "invoices": "Invoices",
    "projects": "Projects",
}


def _matches(name: str, words: list[str]) -> bool:
    lowered = name.lower()
    return all(w in lowered for w in words)


# ------------------------------------------------------------------ reports


def _parse_report(payload: Any) -> tuple[list[str], list[str], list[dict[str, Any]]] | None:
    """Return (identifiers, headers, rows) or None when the shape is unknown."""
    if isinstance(payload, Mapping) and isinstance(payload.get("columns"), list):
        columns = [c for c in payload["columns"] if isinstance(c, Mapping)]
        identifiers = [str(c.get("identifier", "")) for c in columns]
        headers = [str(c.get("display_value") or c.get("identifier", "")) for c in columns]
        row_keys = sorted(
            (k for k in payload if k != "columns" and str(k).isdigit()), key=lambda k: int(k)
        )
        rows = []
        for key in row_keys:
            cells = {
                str(cell.get("identifier")): cell.get("display_value", cell.get("value"))
                for cell in payload[key]
                if isinstance(cell, Mapping)
            }
            rows.append({h: cells.get(i, "") for i, h in zip(identifiers, headers, strict=True)})
        return identifiers, headers, rows
    if isinstance(payload, str):
        try:
            text = base64.b64decode(payload, validate=True).decode("utf-8-sig")
        except (binascii.Error, UnicodeDecodeError):
            return None
        table = [row for row in csv.reader(io.StringIO(text)) if row]
        if not table:
            return [], [], []
        headers = table[0]
        rows = [dict(zip(headers, row, strict=False)) for row in table[1:]]
        return [], headers, rows
    return None


def _render_report(report_id: str, payload: Any, max_rows: int, response_format: str) -> str:
    parsed = _parse_report(payload)
    if parsed is None:
        return to_json(compact(payload))
    identifiers, headers, rows = parsed
    shown = rows[:max_rows]
    if response_format == "json":
        result: dict[str, Any] = {
            "columns": headers,
            "rows": shown,
            "total_rows": len(rows),
            "truncated": len(rows) > len(shown),
        }
        if identifiers:
            result["column_keys"] = identifiers
        return to_json(result)
    lines = [
        f"# Report {report_id}",
        "",
        f"{len(rows)} rows"
        + (
            f", showing the first {len(shown)} (raise max_rows to see more)."
            if len(rows) > len(shown)
            else "."
        ),
    ]
    if identifiers:
        lines += [
            "",
            "Column keys (pass a subset as report_keys to narrow the report): "
            + ", ".join(identifiers),
        ]
    if headers:
        body = [[md_cell(r.get(h, "")) for h in headers] for r in shown]
        lines += ["", *markdown_table([md_cell(h) for h in headers], body)]
    return "\n".join(lines)


def register(server: MCPServer, client: InvoiceNinjaClient, poll_interval: float) -> None:
    async def fetch_report(report_id: str, max_wait: int) -> Any | None:
        deadline = time.monotonic() + max_wait
        while True:
            try:
                return await client.post(f"/reports/preview/{report_id}", json={})
            except InvoiceNinjaError as exc:
                if exc.status != 409:
                    raise
            if time.monotonic() >= deadline:
                return None
            await anyio.sleep(poll_interval)

    def pending_message(report_id: str) -> str:
        return (
            f"The report is still being generated (report_id: {report_id}). Call "
            f"invoiceninja_get_report_result with report_id='{report_id}' in a little while. "
            "Results stay available for one hour and can be read once."
        )

    @tool_errors
    async def ping() -> str:
        info = await client.get("/ping")
        return (
            f"Connected to Invoice Ninja at {client.base_url}: company "
            f"'{info.get('company_name', '?')}', API user '{info.get('user_name', '?')}'."
        )

    @tool_errors
    async def get_statics(
        section: Annotated[StaticsSection, Field(description="Which lookup table to return")],
        search: Annotated[
            str | None, Field(description="Case-insensitive text to filter entries by")
        ] = None,
        limit: Annotated[int, Field(ge=1, le=500, description="Maximum entries")] = 100,
    ) -> str:
        statics = await client.get("/statics")
        entries = statics.get(section) or []
        if search:
            needle = search.lower()
            entries = [e for e in entries if needle in to_json(e).lower()]
        return to_json({section: compact(entries[:limit]), "total": len(entries)})

    @tool_errors
    async def search(
        query: Annotated[
            str,
            Field(
                min_length=1,
                max_length=200,
                description="Words to look for in client names, contact names/emails, "
                "invoice numbers and project names",
            ),
        ],
        limit: Annotated[int, Field(ge=1, le=100, description="Max matches per group")] = 20,
        response_format: ResponseFormat = "markdown",
    ) -> str:
        payload = await client.post("/search", json={"search": query})
        words = query.lower().split()
        groups: dict[str, list[dict[str, Any]]] = {}
        totals: dict[str, int] = {}
        for key in _SEARCH_GROUPS:
            items = [
                {
                    "name": i.get("name"),
                    "id": i.get("id"),
                    "type": str(i.get("type", "")).strip("/"),
                }
                for i in payload.get(key) or []
                if isinstance(i, Mapping) and _matches(str(i.get("name", "")), words)
            ]
            if items:
                groups[key] = items[:limit]
                totals[key] = len(items)
        if response_format == "json":
            return to_json({"results": groups, "totals": totals})
        if not groups:
            return f"No matches for '{query}'. Try fewer or different words, or a list tool."
        lines = [f"# Search results for '{query}'"]
        for key, items in groups.items():
            header = f"## {_SEARCH_GROUPS[key]} ({totals[key]})"
            lines += ["", header, *[f"- {i['name']} ({i['id']})" for i in items]]
            if totals[key] > len(items):
                lines.append(f"- … {totals[key] - len(items)} more (raise limit)")
        lines += ["", "Contact matches point to their client's id."]
        return "\n".join(lines)

    @tool_errors
    async def dashboard_totals(
        start_date: IsoDate = None,
        end_date: IsoDate = None,
        response_format: ResponseFormat = "markdown",
    ) -> str:
        body = {k: v for k, v in {"start_date": start_date, "end_date": end_date}.items() if v}
        payload = await client.post("/charts/totals", json=body)
        if response_format == "json":
            return to_json(payload)
        currencies = payload.get("currencies") or {}
        lines = [
            "# Dashboard totals "
            f"({payload.get('start_date', start_date or '?')} → "
            f"{payload.get('end_date', end_date or '?')})",
            "",
            "| Currency | Invoiced | Paid | Outstanding (count) | Expenses |",
            "|---|---|---|---|---|",
        ]
        for currency_id, code in currencies.items():
            block = payload.get(str(currency_id)) or {}

            def amount(section: str, field: str, block: Mapping[str, Any] = block) -> str:
                value = (block.get(section) or {}).get(field)
                return f"{float(value):,.2f}" if value not in (None, "") else "0.00"

            count = (block.get("outstanding") or {}).get("outstanding_count", 0)
            lines.append(
                f"| {code} | {amount('invoices', 'invoiced_amount')} | "
                f"{amount('revenue', 'paid_to_date')} | "
                f"{amount('outstanding', 'amount')} ({count}) | {amount('expenses', 'amount')} |"
            )
        if not currencies:
            lines.append("| — | 0.00 | 0.00 | 0.00 (0) | 0.00 |")
        return "\n".join(lines)

    @tool_errors
    async def run_report(
        report: Annotated[ReportType, Field(description="Which report to run")],
        date_range: Annotated[
            DateRange, Field(description="Period; 'custom' requires start_date and end_date")
        ] = "this_year",
        start_date: IsoDate = None,
        end_date: IsoDate = None,
        date_key: Annotated[
            str | None,
            Field(description="Date column the period applies to, e.g. 'date' or 'due_date'"),
        ] = None,
        report_keys: Annotated[
            list[str] | None,
            Field(
                description="Columns to include, e.g. ['invoice.number','invoice.balance']. "
                "Empty = all columns (keys are listed in every result)"
            ),
        ] = None,
        client_id: Annotated[
            str | None, Field(description="Restrict to one client (hashed id)")
        ] = None,
        include_deleted: bool = False,
        is_income_billed: Annotated[
            bool,
            Field(
                description="profitloss only: true = income from invoices, false = from payments"
            ),
        ] = True,
        include_tax: Annotated[bool, Field(description="profitloss only: include taxes")] = False,
        extra: Annotated[
            dict[str, Any] | None,
            Field(description="Additional report parameters, e.g. {'product_key': 'X'}"),
        ] = None,
        max_wait_seconds: MaxWait = 60,
        max_rows: MaxRows = 100,
        response_format: ResponseFormat = "markdown",
    ) -> str:
        if date_range == "custom" and not (start_date and end_date):
            raise ToolError("date_range='custom' requires both start_date and end_date.")
        body: dict[str, Any] = dict(extra or {})
        body.update(
            {
                "date_range": date_range,
                "report_keys": report_keys or [],
                "send_email": False,
                "include_deleted": include_deleted,
                "output": "json",
            }
        )
        if date_range == "custom":
            body.update({"start_date": start_date, "end_date": end_date})
        if date_key:
            body["date_key"] = date_key
        if client_id:
            body["client_id"] = client_id
        if report == "profitloss":
            body.update({"is_income_billed": is_income_billed, "include_tax": include_tax})
        started = await client.post(f"/reports/{report}", json=body)
        report_id = str(started.get("message", "")) if isinstance(started, Mapping) else ""
        if not report_id or " " in report_id:
            raise ToolError(f"Invoice Ninja did not start the report: {started!r}")
        payload = await fetch_report(report_id, max_wait_seconds)
        if payload is None:
            return pending_message(report_id)
        return _render_report(report_id, payload, max_rows, response_format)

    @tool_errors
    async def get_report_result(
        report_id: Annotated[
            str, Field(min_length=1, max_length=100, description="Id from run_report")
        ],
        max_wait_seconds: MaxWait = 30,
        max_rows: MaxRows = 100,
        response_format: ResponseFormat = "markdown",
    ) -> str:
        payload = await fetch_report(report_id, max_wait_seconds)
        if payload is None:
            return pending_message(report_id)
        return _render_report(report_id, payload, max_rows, response_format)

    ro = READ_ONLY
    server.add_tool(
        ping,
        name="invoiceninja_ping",
        description="Check the connection and show which company and user the API token uses.",
        annotations=annotations("Check connection", **ro),
        structured_output=False,
    )
    server.add_tool(
        get_statics,
        name="invoiceninja_get_statics",
        description=(
            "Look up static reference data (currencies, countries, payment types, languages, "
            "timezones, industries, sizes, date formats, gateways) to translate ids such as "
            "currency_id, country_id or type_id into names."
        ),
        annotations=annotations("Look up static data", **ro),
        structured_output=False,
    )
    server.add_tool(
        search,
        name="invoiceninja_search",
        description=(
            "Quickly find clients, client contacts, invoices and projects by name, email or "
            "number and get their ids. Start here when the user mentions a record by name."
        ),
        annotations=annotations("Search", **ro),
        structured_output=False,
    )
    server.add_tool(
        dashboard_totals,
        name="invoiceninja_dashboard_totals",
        description=(
            "Totals per currency for a period: invoiced, paid, outstanding (with count) and "
            "expenses. Defaults to the instance's default period when dates are omitted."
        ),
        annotations=annotations("Dashboard totals", **ro),
        structured_output=False,
    )
    server.add_tool(
        run_report,
        name="invoiceninja_run_report",
        description=(
            "Run an Invoice Ninja report (invoices, payments, expenses, profit & loss, aged "
            "receivables, tax summaries, product sales, …) and return its rows. Best for "
            "aggregates over many records. Reports are generated asynchronously: if not ready "
            "within max_wait_seconds a report_id is returned for invoiceninja_get_report_result."
        ),
        annotations=annotations("Run report", read_only_hint=True, destructive_hint=False),
        structured_output=False,
    )
    server.add_tool(
        get_report_result,
        name="invoiceninja_get_report_result",
        description="Fetch the rows of a report started by invoiceninja_run_report.",
        annotations=annotations("Get report result", read_only_hint=True, destructive_hint=False),
        structured_output=False,
    )
