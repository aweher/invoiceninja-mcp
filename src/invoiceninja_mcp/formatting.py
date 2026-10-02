"""Turn raw API payloads into LLM-friendly JSON or Markdown."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from typing import Any

from invoiceninja_mcp.entities import FREQUENCIES, Column, EntitySpec

CHARACTER_LIMIT = 25_000

_SENSITIVE_KEYS = {
    "password",
    "token",
    "gateway_tokens",
    "google_2fa_secret",
    "oauth_user_token",
    "oauth_user_refresh_token",
    "oauth_provider_id",
}
_TRUNCATE_CELL = 60


def _is_sensitive(key: str) -> bool:
    return key in _SENSITIVE_KEYS or key.endswith(("_secret", "_password"))


def redact(value: Any) -> Any:
    """Drop secrets (2FA seeds, OAuth tokens, gateway tokens…) at any depth."""
    if isinstance(value, Mapping):
        return {k: redact(v) for k, v in value.items() if not _is_sensitive(str(k))}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or (isinstance(value, (list, dict)) and not value)


def compact(value: Any) -> Any:
    """Recursively drop None, empty strings, empty lists and empty dicts (keeps 0 and False)."""
    if isinstance(value, Mapping):
        out = {k: compact(v) for k, v in value.items()}
        return {k: v for k, v in out.items() if not _is_empty(v)}
    if isinstance(value, list):
        items = [compact(v) for v in value]
        return [v for v in items if not _is_empty(v)]
    return value


def project(record: Mapping[str, Any], fields: Iterable[str]) -> dict[str, Any]:
    wanted = {"id", *fields}
    return {k: v for k, v in record.items() if k in wanted}


def _epoch_to_iso(value: Any) -> Any:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    if value <= 0:
        return None
    return datetime.fromtimestamp(value, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _related_name(related: Mapping[str, Any]) -> Any:
    return related.get("display_name") or related.get("name") or related.get("number")


def normalize_record(
    spec: EntitySpec, record: Mapping[str, Any], keep: Iterable[str] = ()
) -> dict[str, Any]:
    """Redact secrets, resolve auto-included relations to names, add readable labels."""
    keep = set(keep)
    rec: dict[str, Any] = dict(redact(record))
    for rel in spec.name_includes:
        related = rec.get(rel)
        if isinstance(related, Mapping):
            rec[f"{rel}_name"] = _related_name(related)
            if rel not in keep:
                del rec[rel]
    for key, value in list(rec.items()):
        if key.endswith("_at"):
            rec[key] = _epoch_to_iso(value)
    if spec.status_map and rec.get("status_id") is not None:
        rec["status"] = spec.status_map.get(str(rec["status_id"]), str(rec["status_id"]))
    if rec.get("frequency_id") is not None:
        rec["frequency"] = FREQUENCIES.get(str(rec["frequency_id"]), str(rec["frequency_id"]))
    return rec


# ---------------------------------------------------------------- markdown


def _money(value: Any) -> str:
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def _duration(value: Any) -> str:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return str(value)
    hours, rest = divmod(seconds, 3600)
    return f"{hours}h {rest // 60:02d}m"


def _date(value: Any) -> str:
    text = str(value)
    if "T" in text:
        return text.replace("T", " ")[:16]
    return text


def _is_overdue(spec: EntitySpec, rec: Mapping[str, Any], today: date) -> bool:
    if spec.path != "invoices" or str(rec.get("status_id")) not in {"2", "3"}:
        return False
    try:
        due = date.fromisoformat(str(rec.get("due_date")))
        return due < today and float(rec.get("balance") or 0) > 0
    except ValueError:
        return False


def _cell(
    spec: EntitySpec, column: Column, rec: Mapping[str, Any], today: date, *, table: bool
) -> str:
    value = rec.get(column.key)
    if _is_empty(value):
        return ""
    if column.kind == "money":
        text = _money(value)
    elif column.kind == "status":
        text = spec.status_map.get(str(value), str(value))
        if _is_overdue(spec, rec, today):
            text += " (overdue)"
    elif column.kind == "frequency":
        text = FREQUENCIES.get(str(value), str(value))
    elif column.kind == "date":
        text = _date(value)
    elif column.kind == "duration":
        text = _duration(value)
    else:
        text = str(value)
    text = " ".join(text.split())
    if table:
        if column.kind == "truncate" and len(text) > _TRUNCATE_CELL:
            text = text[: _TRUNCATE_CELL - 1] + "…"
        text = text.replace("|", "\\|")
    return text


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return lines


def render_list_markdown(
    spec: EntitySpec,
    records: list[dict[str, Any]],
    pagination: Mapping[str, Any],
    today: date | None = None,
) -> str:
    today = today or date.today()
    title = spec.label[0].upper() + spec.label[1:]
    if not records:
        return f"# {title}\n\nNo {spec.label} found with these filters."

    page = int(pagination.get("current_page") or 1)
    pages = int(pagination.get("total_pages") or 1)
    total = pagination.get("total", len(records))
    lines = [f"# {title} — page {page}/{pages}, {total} total", ""]
    headers = ["ID", *[c.header for c in spec.columns]]
    rows = [
        [str(r.get("id", "")), *[_cell(spec, c, r, today, table=True) for c in spec.columns]]
        for r in records
    ]
    lines += _table(headers, rows)
    if page < pages:
        lines += ["", f"More results available: call again with page={page + 1}."]
    return "\n".join(lines)


_NESTED_TABLES: dict[str, tuple[list[str], list[tuple[str, str]]]] = {
    "line_items": (
        ["Product", "Description", "Qty", "Cost", "Total"],
        [
            ("product_key", "text"),
            ("notes", "text"),
            ("quantity", "text"),
            ("cost", "money"),
            ("line_total", "money"),
        ],
    ),
    "contacts": (
        ["First name", "Last name", "Email", "Phone"],
        [("first_name", "text"), ("last_name", "text"), ("email", "text"), ("phone", "text")],
    ),
}


def render_record_markdown(
    spec: EntitySpec, record: Mapping[str, Any], today: date | None = None
) -> str:
    today = today or date.today()
    rec = compact(record)
    singular = spec.singular.replace("_", " ")
    title = rec.get(spec.title_field) or rec.get("number") or rec.get("name") or ""
    lines = [f"# {singular[0].upper() + singular[1:]} {title} ({rec.get('id', '?')})".strip(), ""]

    shown = {"id", "status", "frequency"}
    for column in spec.columns:
        text = _cell(spec, column, rec, today, table=False)
        if text:
            lines.append(f"- **{column.header}:** {text}")
        shown.add(column.key)

    details: list[str] = []
    nested: list[str] = []
    for key, value in rec.items():
        if key in shown:
            continue
        if isinstance(value, (dict, list)):
            if key not in _NESTED_TABLES:
                nested.append(key)
            continue
        details.append(f"- **{key}:** {' '.join(str(value).split())}")
    if details:
        lines += ["", "## Details", *details]

    for key, (headers, cols) in _NESTED_TABLES.items():
        items = rec.get(key)
        if not isinstance(items, list) or not items:
            continue
        rows = []
        for item in items:
            if not isinstance(item, Mapping):
                continue
            row = []
            for field, kind in cols:
                value = item.get(field, "")
                text = _money(value) if kind == "money" and value != "" else str(value)
                row.append(" ".join(text.split()).replace("|", "\\|"))
            rows.append(row)
        lines += ["", f"## {key.replace('_', ' ').capitalize()}", *_table(headers, rows)]

    if nested:
        lines += [
            "",
            f"_Nested data omitted ({', '.join(sorted(nested))}); "
            "use response_format='json' to see it._",
        ]
    return "\n".join(lines)


def truncate(text: str, limit: int = CHARACTER_LIMIT) -> str:
    if len(text) <= limit:
        return text
    note = (
        f"\n\n[Response truncated from {len(text):,} to {limit:,} characters. "
        "Narrow the query: use filters, a smaller per_page, the 'fields' parameter, "
        "or response_format='markdown'.]"
    )
    return text[: max(0, limit - len(note))] + note
