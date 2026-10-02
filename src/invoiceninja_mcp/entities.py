"""Declarative registry of the Invoice Ninja entities exposed as MCP tools.

Filter names, status ids and includes were taken from the v5-stable source
(app/Filters/*, app/Models/*, app/Transformers/*).
"""

from __future__ import annotations

from dataclasses import dataclass, field

FREQUENCIES = {
    "1": "daily",
    "2": "weekly",
    "3": "every 2 weeks",
    "4": "every 4 weeks",
    "5": "monthly",
    "6": "every 2 months",
    "7": "quarterly",
    "8": "every 4 months",
    "9": "every 6 months",
    "10": "annually",
    "11": "every 2 years",
    "12": "every 3 years",
}

_INVOICE_STATUS = {
    "1": "draft",
    "2": "sent",
    "3": "partial",
    "4": "paid",
    "5": "cancelled",
    "6": "reversed",
}
_QUOTE_STATUS = {
    "1": "draft",
    "2": "sent",
    "3": "approved",
    "4": "converted",
    "5": "rejected",
    "-1": "expired",
}
_CREDIT_STATUS = {"1": "draft", "2": "sent", "3": "partial", "4": "applied"}
_PAYMENT_STATUS = {
    "1": "pending",
    "2": "cancelled",
    "3": "failed",
    "4": "completed",
    "5": "partially refunded",
    "6": "refunded",
    "-1": "unapplied",
}
_RECURRING_STATUS = {"1": "draft", "2": "active", "3": "paused", "4": "completed", "-1": "pending"}
_PURCHASE_ORDER_STATUS = {
    "1": "draft",
    "2": "sent",
    "3": "accepted",
    "4": "received",
    "5": "cancelled",
}

_COMMON_FILTERS = (
    "created_between / updated_between ('YYYY-MM-DD,YYYY-MM-DD'), "
    "tag_ids (comma separated), assigned_user_ids"
)
_DATED_FILTERS = (
    "date_range ('YYYY-MM-DD,YYYY-MM-DD' on the document date, or "
    "'due_date,YYYY-MM-DD,YYYY-MM-DD' for another column), date (on/after YYYY-MM-DD), "
    "due_date (on/before YYYY-MM-DD), number"
)


@dataclass(frozen=True)
class Column:
    key: str
    header: str
    kind: str = "text"  # text | money | status | frequency | date | duration | truncate


@dataclass(frozen=True)
class EntitySpec:
    path: str  # API path segment, also the plural name used in tool names
    singular: str
    label: str  # human readable plural
    columns: tuple[Column, ...]
    status_map: dict[str, str] = field(default_factory=dict)
    client_status_values: tuple[str, ...] = ()
    extra_filters: str = ""
    # relations auto-included in list/get so names can be shown instead of hashed ids
    name_includes: tuple[str, ...] = ()
    has_client_filter: bool = False
    write_hint: str = ""
    bulk_actions: tuple[str, ...] = ("archive", "restore", "delete")

    @property
    def title_field(self) -> str:
        return self.columns[0].key


_DOC_ACTIONS = ("archive", "restore", "delete", "email", "mark_sent")
_LINE_ITEMS_HINT = (
    "line_items: [{product_key, notes, cost, quantity, tax_name1?, tax_rate1?}], "
    "date (YYYY-MM-DD), due_date, po_number, public_notes, private_notes, discount"
)

CORE_ENTITIES: dict[str, EntitySpec] = {
    spec.path: spec
    for spec in (
        EntitySpec(
            path="clients",
            singular="client",
            label="clients",
            columns=(
                Column("display_name", "Name"),
                Column("number", "Number"),
                Column("balance", "Balance", "money"),
                Column("paid_to_date", "Paid to date", "money"),
                Column("credit_balance", "Credit", "money"),
            ),
            extra_filters=(
                "name, email, number, id_number, vat_number, balance ('gt:0', 'lt:100', "
                "operators lt/lte/gt/gte/eq), between_balance ('10:100'), group "
                "(group settings id), country_id, classification"
            ),
            write_hint=(
                "name, contacts: [{first_name, last_name, email, phone}], address1, city, "
                "state, postal_code, country_id, vat_number, id_number, website, "
                "private_notes, settings: {currency_id}"
            ),
            bulk_actions=("archive", "restore", "delete"),
        ),
        EntitySpec(
            path="invoices",
            singular="invoice",
            label="invoices",
            columns=(
                Column("number", "Number"),
                Column("client_name", "Client"),
                Column("status_id", "Status", "status"),
                Column("date", "Date", "date"),
                Column("due_date", "Due", "date"),
                Column("amount", "Amount", "money"),
                Column("balance", "Balance", "money"),
            ),
            status_map=_INVOICE_STATUS,
            client_status_values=("all", "draft", "paid", "unpaid", "overdue", "cancelled"),
            extra_filters=f"{_DATED_FILTERS}, project_id, private_notes, payable (client_id)",
            name_includes=("client",),
            has_client_filter=True,
            write_hint=f"client_id (required), {_LINE_ITEMS_HINT}",
            bulk_actions=(*_DOC_ACTIONS, "mark_paid", "cancel", "auto_bill"),
        ),
        EntitySpec(
            path="quotes",
            singular="quote",
            label="quotes",
            columns=(
                Column("number", "Number"),
                Column("client_name", "Client"),
                Column("status_id", "Status", "status"),
                Column("date", "Date", "date"),
                Column("due_date", "Valid until", "date"),
                Column("amount", "Amount", "money"),
            ),
            status_map=_QUOTE_STATUS,
            client_status_values=(
                "all",
                "draft",
                "sent",
                "approved",
                "expired",
                "upcoming",
                "converted",
            ),
            extra_filters=_DATED_FILTERS,
            name_includes=("client",),
            has_client_filter=True,
            write_hint=f"client_id (required), {_LINE_ITEMS_HINT}",
            bulk_actions=(*_DOC_ACTIONS, "approve", "convert_to_invoice"),
        ),
        EntitySpec(
            path="credits",
            singular="credit",
            label="credits",
            columns=(
                Column("number", "Number"),
                Column("client_name", "Client"),
                Column("status_id", "Status", "status"),
                Column("date", "Date", "date"),
                Column("amount", "Amount", "money"),
                Column("balance", "Balance", "money"),
            ),
            status_map=_CREDIT_STATUS,
            client_status_values=("all", "draft", "sent", "partial", "applied"),
            extra_filters=f"{_DATED_FILTERS}, applicable (credits usable now)",
            name_includes=("client",),
            has_client_filter=True,
            write_hint=f"client_id (required), {_LINE_ITEMS_HINT}",
            bulk_actions=_DOC_ACTIONS,
        ),
        EntitySpec(
            path="payments",
            singular="payment",
            label="payments",
            columns=(
                Column("number", "Number"),
                Column("client_name", "Client"),
                Column("status_id", "Status", "status"),
                Column("date", "Date", "date"),
                Column("amount", "Amount", "money"),
                Column("applied", "Applied", "money"),
                Column("refunded", "Refunded", "money"),
                Column("transaction_reference", "Reference"),
            ),
            status_map=_PAYMENT_STATUS,
            client_status_values=(
                "all",
                "pending",
                "cancelled",
                "failed",
                "completed",
                "partially_refunded",
                "refunded",
                "partially_unapplied",
            ),
            extra_filters="number, date_range ('YYYY-MM-DD,YYYY-MM-DD')",
            name_includes=("client",),
            has_client_filter=True,
            write_hint=(
                "client_id (required), amount, date, type_id (see statics payment_types), "
                "transaction_reference, invoices: [{invoice_id, amount}]"
            ),
            bulk_actions=("archive", "restore", "delete", "email"),
        ),
        EntitySpec(
            path="recurring_invoices",
            singular="recurring_invoice",
            label="recurring invoices",
            columns=(
                Column("number", "Number"),
                Column("client_name", "Client"),
                Column("status_id", "Status", "status"),
                Column("frequency_id", "Frequency", "frequency"),
                Column("next_send_date", "Next send", "date"),
                Column("amount", "Amount", "money"),
                Column("remaining_cycles", "Remaining cycles"),
            ),
            status_map=_RECURRING_STATUS,
            client_status_values=("all", "draft", "active", "paused", "completed"),
            extra_filters=(
                "number, product_key, frequency_id (1 daily … 5 monthly … 10 annually), "
                "next_send_between ('YYYY-MM-DD|YYYY-MM-DD')"
            ),
            name_includes=("client",),
            has_client_filter=True,
            write_hint=(
                f"client_id (required), frequency_id (5 = monthly), remaining_cycles "
                f"(-1 = endless), next_send_date, {_LINE_ITEMS_HINT}"
            ),
            bulk_actions=("archive", "restore", "delete", "start", "stop", "send_now"),
        ),
        EntitySpec(
            path="products",
            singular="product",
            label="products",
            columns=(
                Column("product_key", "Product"),
                Column("notes", "Description", "truncate"),
                Column("price", "Price", "money"),
                Column("cost", "Cost", "money"),
                Column("in_stock_quantity", "In stock"),
            ),
            extra_filters="product_key",
            write_hint="product_key (required), notes, price, cost, quantity, tax_name1, tax_rate1",
        ),
        EntitySpec(
            path="expenses",
            singular="expense",
            label="expenses",
            columns=(
                Column("number", "Number"),
                Column("date", "Date", "date"),
                Column("vendor_name", "Vendor"),
                Column("client_name", "Client"),
                Column("amount", "Amount", "money"),
                Column("public_notes", "Notes", "truncate"),
            ),
            client_status_values=(
                "all",
                "logged",
                "pending",
                "invoiced",
                "uninvoiced",
                "paid",
                "unpaid",
                "uncategorized",
            ),
            extra_filters=(
                "number, amount, categories (category ids, comma separated), vendor_ids, "
                "project_ids, payment_type, has_invoices, date_range ('YYYY-MM-DD,YYYY-MM-DD')"
            ),
            name_includes=("client", "vendor"),
            has_client_filter=True,
            write_hint=(
                "amount, date, vendor_id, client_id, category_id, public_notes, "
                "private_notes, should_be_invoiced, payment_date, payment_type_id"
            ),
        ),
        EntitySpec(
            path="recurring_expenses",
            singular="recurring_expense",
            label="recurring expenses",
            columns=(
                Column("number", "Number"),
                Column("vendor_name", "Vendor"),
                Column("status_id", "Status", "status"),
                Column("frequency_id", "Frequency", "frequency"),
                Column("next_send_date", "Next", "date"),
                Column("amount", "Amount", "money"),
            ),
            status_map=_RECURRING_STATUS,
            client_status_values=("all", "logged", "pending", "invoiced", "paid", "unpaid"),
            extra_filters="number",
            name_includes=("client", "vendor"),
            has_client_filter=True,
            write_hint="amount, frequency_id, next_send_date, vendor_id, category_id, public_notes",
        ),
        EntitySpec(
            path="vendors",
            singular="vendor",
            label="vendors",
            columns=(
                Column("display_name", "Name"),
                Column("number", "Number"),
                Column("phone", "Phone"),
                Column("website", "Website"),
            ),
            extra_filters="number",
            write_hint=(
                "name, contacts: [{first_name, last_name, email}], address1, city, "
                "country_id, vat_number, currency_id"
            ),
        ),
        EntitySpec(
            path="projects",
            singular="project",
            label="projects",
            columns=(
                Column("name", "Name"),
                Column("number", "Number"),
                Column("client_name", "Client"),
                Column("due_date", "Due", "date"),
                Column("budgeted_hours", "Budget h"),
                Column("current_hours", "Logged h"),
            ),
            extra_filters="number, assigned_user (user id)",
            name_includes=("client",),
            has_client_filter=True,
            write_hint="name (required), client_id (required), due_date, budgeted_hours, task_rate",
        ),
        EntitySpec(
            path="tasks",
            singular="task",
            label="tasks",
            columns=(
                Column("number", "Number"),
                Column("description", "Description", "truncate"),
                Column("client_name", "Client"),
                Column("project_name", "Project"),
                Column("status_name", "Status"),
                Column("duration", "Duration", "duration"),
                Column("is_running", "Running"),
            ),
            client_status_values=("all", "invoiced", "uninvoiced", "is_running", "overdue"),
            extra_filters=(
                "number, project_tasks (project id), project_ids, task_status (status ids), "
                "user_id, assigned_user, activity_dates"
            ),
            name_includes=("client", "project", "status"),
            has_client_filter=True,
            write_hint=(
                "description, client_id, project_id, rate, "
                "time_log (JSON string of [[start_unix, end_unix], ...])"
            ),
            bulk_actions=("archive", "restore", "delete", "start", "stop"),
        ),
        EntitySpec(
            path="purchase_orders",
            singular="purchase_order",
            label="purchase orders",
            columns=(
                Column("number", "Number"),
                Column("vendor_name", "Vendor"),
                Column("status_id", "Status", "status"),
                Column("date", "Date", "date"),
                Column("due_date", "Due", "date"),
                Column("amount", "Amount", "money"),
                Column("balance", "Balance", "money"),
            ),
            status_map=_PURCHASE_ORDER_STATUS,
            client_status_values=("all", "draft", "sent", "accepted", "cancelled"),
            extra_filters=f"{_DATED_FILTERS}, vendor_id",
            name_includes=("vendor",),
            write_hint=f"vendor_id (required), {_LINE_ITEMS_HINT}",
            bulk_actions=(*_DOC_ACTIONS, "cancel"),
        ),
    )
}

# Reference / secondary data exposed through the generic record tools.
SECONDARY_ENTITIES: dict[str, EntitySpec] = {
    spec.path: spec
    for spec in (
        EntitySpec(
            "tax_rates", "tax_rate", "tax rates", (Column("name", "Name"), Column("rate", "Rate"))
        ),
        EntitySpec(
            "payment_terms",
            "payment_term",
            "payment terms",
            (Column("name", "Name"), Column("num_days", "Days")),
        ),
        EntitySpec(
            "expense_categories",
            "expense_category",
            "expense categories",
            (Column("name", "Name"),),
        ),
        EntitySpec(
            "task_statuses",
            "task_status",
            "task statuses",
            (Column("name", "Name"), Column("status_order", "Order")),
        ),
        EntitySpec("group_settings", "group_setting", "client groups", (Column("name", "Name"),)),
        EntitySpec(
            "designs",
            "design",
            "designs",
            (Column("name", "Name"), Column("is_custom", "Custom"), Column("is_active", "Active")),
        ),
        EntitySpec(
            "documents",
            "document",
            "documents",
            (Column("name", "Name"), Column("type", "Type"), Column("size", "Size")),
        ),
        EntitySpec(
            "bank_transactions",
            "bank_transaction",
            "bank transactions",
            (
                Column("date", "Date", "date"),
                Column("description", "Description", "truncate"),
                Column("amount", "Amount", "money"),
                Column("base_type", "Type"),
                Column("participant_name", "Participant"),
            ),
        ),
        EntitySpec(
            "activities",
            "activity",
            "activity log",
            (
                Column("created_at", "When", "date"),
                Column("activity_type_id", "Type"),
                Column("notes", "Notes", "truncate"),
            ),
        ),
        EntitySpec("tags", "tag", "tags", (Column("name", "Name"),)),
        EntitySpec("locations", "location", "locations", (Column("name", "Name"),)),
        EntitySpec(
            "subscriptions",
            "subscription",
            "subscriptions",
            (Column("name", "Name"), Column("price", "Price", "money")),
        ),
        EntitySpec(
            "recurring_quotes",
            "recurring_quote",
            "recurring quotes",
            (
                Column("number", "Number"),
                Column("status_id", "Status", "status"),
                Column("frequency_id", "Frequency", "frequency"),
                Column("amount", "Amount", "money"),
            ),
            status_map=_RECURRING_STATUS,
        ),
        EntitySpec(
            "users",
            "user",
            "users",
            (Column("first_name", "First"), Column("last_name", "Last"), Column("email", "Email")),
        ),
    )
}

ALL_ENTITIES: dict[str, EntitySpec] = {**CORE_ENTITIES, **SECONDARY_ENTITIES}

COMMON_FILTERS_DOC = _COMMON_FILTERS
