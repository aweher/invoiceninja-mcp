"""MCP server wiring and command-line entry point."""

import argparse
import logging
import sys
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

from mcp.server import MCPServer

from invoiceninja_mcp import __version__
from invoiceninja_mcp.client import InvoiceNinjaClient
from invoiceninja_mcp.config import ConfigError, Settings
from invoiceninja_mcp.tools import misc, read, write

_LOOPBACK = {"127.0.0.1", "localhost", "::1"}

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
    if settings.enable_writes:
        write.register(server, http)
    return server


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="invoiceninja-mcp",
        description="MCP server for Invoice Ninja v5. Configured through INVOICENINJA_* "
        "environment variables (see README).",
    )
    parser.add_argument(
        "--transport", choices=["stdio", "streamable-http"], default="stdio", help="default: stdio"
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind address")
    parser.add_argument("--port", type=int, default=8000, help="HTTP port")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)
    # httpx logs every request at INFO; keep stderr for things that matter
    logging.getLogger("httpx").setLevel(logging.WARNING)

    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        print(f"invoiceninja-mcp: configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from None

    server = build_server(settings)
    if args.transport == "stdio":
        server.run("stdio")
        return

    if args.host not in _LOOPBACK:
        print(
            f"WARNING: the MCP endpoint has no authentication and will be reachable on "
            f"{args.host}:{args.port}. Anyone who can connect can read your Invoice Ninja data"
            + (" and change it" if settings.enable_writes else "")
            + ". Put it behind an authenticating reverse proxy or bind to 127.0.0.1.",
            file=sys.stderr,
        )
    server.run(
        "streamable-http",
        host=args.host,
        port=args.port,
        stateless_http=True,
        json_response=True,
    )
