from datetime import date

from invoiceninja_mcp.entities import CORE_ENTITIES, SECONDARY_ENTITIES
from invoiceninja_mcp.formatting import (
    compact,
    normalize_record,
    project,
    redact,
    render_list_markdown,
    render_record_markdown,
    truncate,
)

INVOICES = CORE_ENTITIES["invoices"]
TODAY = date(2026, 10, 2)


def invoice(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "Wpmbk5ezJn",
        "number": "INV-0001",
        "status_id": "2",
        "date": "2026-09-01",
        "due_date": "2026-09-15",
        "amount": 1200,
        "balance": "1200.00",
        "client_id": "mWZdPwbKgR",
        "client": {"id": "mWZdPwbKgR", "name": "Acme", "display_name": "Acme Corp", "x": 1},
        "created_at": 1790943467,
        "archived_at": 0,
        "private_notes": "",
        "line_items": [
            {
                "product_key": "Hosting",
                "notes": "Monthly",
                "quantity": 1,
                "cost": 1200,
                "line_total": 1200,
            },
        ],
    }
    base.update(overrides)
    return base


def test_redact_drops_secrets_recursively() -> None:
    data = {
        "email": "a@b.c",
        "google_2fa_secret": "XYZ",
        "oauth_user_token": "tok",
        "password": "p",
        "nested": [{"token": "t", "keep": 1, "webhook_secret": "s"}],
        "gateway_tokens": [{"token": "cus_1"}],
    }
    assert redact(data) == {"email": "a@b.c", "nested": [{"keep": 1}]}


def test_compact_removes_empty_values_but_keeps_zero_and_false() -> None:
    data = {"a": None, "b": "", "c": [], "d": {}, "e": 0, "f": False, "g": {"h": None, "i": 1}}
    assert compact(data) == {"e": 0, "f": False, "g": {"i": 1}}


def test_project_keeps_id_and_requested_fields() -> None:
    assert project({"id": "1", "a": 1, "b": 2}, ["b"]) == {"id": "1", "b": 2}


def test_normalize_collapses_includes_and_adds_labels() -> None:
    rec = normalize_record(INVOICES, invoice())
    assert rec["client_name"] == "Acme Corp"
    assert "client" not in rec
    assert rec["status"] == "sent"
    assert rec["created_at"] == "2026-10-02T12:17:47Z"
    assert rec["archived_at"] is None


def test_normalize_keeps_include_when_requested() -> None:
    rec = normalize_record(INVOICES, invoice(), keep=("client",))
    assert rec["client"]["name"] == "Acme"
    assert rec["client_name"] == "Acme Corp"


def test_normalize_frequency_label() -> None:
    rec = normalize_record(CORE_ENTITIES["recurring_invoices"], {"id": "1", "frequency_id": "5"})
    assert rec["frequency"] == "monthly"


def test_list_markdown_has_table_and_pagination_hint() -> None:
    records = [normalize_record(INVOICES, invoice())]
    pagination = {"total": 26, "count": 1, "per_page": 1, "current_page": 1, "total_pages": 26}
    md = render_list_markdown(INVOICES, records, pagination, today=TODAY)
    assert "# Invoices" in md
    assert "26 total" in md
    assert "| ID | Number | Client | Status |" in md
    assert "| Wpmbk5ezJn | INV-0001 | Acme Corp | sent (overdue) |" in md
    assert "1,200.00" in md
    assert "page=2" in md


def test_list_markdown_last_page_has_no_next_hint() -> None:
    pagination = {"total": 1, "count": 1, "per_page": 20, "current_page": 1, "total_pages": 1}
    md = render_list_markdown(INVOICES, [normalize_record(INVOICES, invoice())], pagination)
    assert "page=2" not in md


def test_list_markdown_empty() -> None:
    md = render_list_markdown(INVOICES, [], {"total": 0, "current_page": 1, "total_pages": 0})
    assert "No invoices found" in md


def test_paid_invoice_is_not_overdue() -> None:
    rec = normalize_record(INVOICES, invoice(status_id="4", balance=0))
    md = render_list_markdown(INVOICES, [rec], {}, today=TODAY)
    assert "| paid |" in md


def test_markdown_escapes_pipes_and_newlines() -> None:
    products = CORE_ENTITIES["products"]
    rec = {"id": "p1", "product_key": "A|B", "notes": "line1\nline2", "price": 3}
    md = render_list_markdown(products, [rec], {})
    assert "A\\|B" in md
    assert "line1 line2" in md


def test_task_duration_is_human_readable() -> None:
    tasks = CORE_ENTITIES["tasks"]
    md = render_list_markdown(tasks, [{"id": "t", "number": "1", "duration": 5430}], {})
    assert "1h 30m" in md


def test_record_markdown_shows_fields_and_line_items() -> None:
    md = render_record_markdown(INVOICES, normalize_record(INVOICES, invoice()))
    assert md.startswith("# Invoice INV-0001 (Wpmbk5ezJn)")
    assert "- **Client:** Acme Corp" in md
    assert "- **client_id:** mWZdPwbKgR" in md
    assert "## Line items" in md
    assert "| Hosting | Monthly | 1 | 1,200.00 | 1,200.00 |" in md
    assert "private_notes" not in md


def test_record_markdown_for_secondary_entity() -> None:
    spec = SECONDARY_ENTITIES["tax_rates"]
    md = render_record_markdown(spec, {"id": "t1", "name": "VAT", "rate": 21})
    assert "# Tax rate VAT (t1)" in md


def test_truncate_short_text_untouched() -> None:
    assert truncate("abc", 10) == "abc"


def test_truncate_long_text_appends_guidance() -> None:
    out = truncate("x" * 1000, 400)
    assert len(out) <= 400
    assert out.startswith("x" * 10)
    assert "truncated" in out
    assert "per_page" in out
