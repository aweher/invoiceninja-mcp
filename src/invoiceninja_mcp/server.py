"""MCP server wiring and command-line entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server import MCPServer

from invoiceninja_mcp import __version__
from invoiceninja_mcp.client import InvoiceNinjaClient
from invoiceninja_mcp.config import Settings
from invoiceninja_mcp.tools import misc, read

INSTRUCTIONS = """\
Tools for reading (and, if enabled, changing) data in an Invoice Ninja v5 instance.
- Record ids are hashed strings (e.g. 'Opnel5aKBz'). Find them with invoiceninja_search or a \
list tool before calling a get tool.
- List tools paginate (per_page up to 100); check the pagination hint before concluding.
- Amounts are in each client's currency; invoiceninja_get_statics resolves currency, country \
and payment type ids.
- For totals across many records prefer invoiceninja_run_report or \
invoiceninja_dashboard_totals over paging through lists.
"""


def build_server(
    settings: Settings,
    client: InvoiceNinjaClient | None = None,
    *,
    report_poll_interval: float = 1.0,
) -> MCPServer:
    owns_client = client is None
    http = client or InvoiceNinjaClient(settings)

    @asynccontextmanager
    async def lifespan(_: MCPServer) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if owns_client:
                await http.aclose()

    server = MCPServer(
        "invoiceninja_mcp",
        version=__version__,
        instructions=INSTRUCTIONS,
        lifespan=lifespan,
    )
    misc.register(server, http, report_poll_interval)
    read.register(server, http)
    return server
