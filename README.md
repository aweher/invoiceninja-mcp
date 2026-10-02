# invoiceninja-mcp

Servidor [MCP](https://modelcontextprotocol.io) para que un LLM (Claude Desktop, Claude Code o cualquier cliente MCP) consulte —y, si lo habilitás explícitamente, modifique— los datos de una instancia de **Invoice Ninja v5** a través de su [API REST](https://api-docs.invoicing.co/).

- **Solo lectura por defecto.** Las herramientas de escritura no se registran salvo que `INVOICENINJA_ENABLE_WRITES=true`.
- Los secretos que devuelve la API (semillas 2FA, tokens OAuth, tokens de gateways, contraseñas) y los links "al portador" (login sin contraseña al portal de clientes, links de ver/pagar facturas, claves de contacto) se eliminan de todas las respuestas. El token de la API nunca aparece en la salida.
- Respuestas en Markdown legible (nombres de cliente y estados resueltos, fechas legibles) o JSON compacto con proyección de campos.

## Requisitos

- Python ≥ 3.12 y [uv](https://docs.astral.sh/uv/)
- Un token de API de Invoice Ninja: *Settings → Account Management → API Tokens*

## Instalación

```bash
git clone <este repo> invoiceninja-mcp
cd invoiceninja-mcp
uv sync
```

## Configuración

Variables de entorno (plantilla en `.env.example`; el servidor no lee archivos `.env`, las variables las pasa el cliente MCP o el shell):

| Variable | Obligatoria | Default | Descripción |
|---|---|---|---|
| `INVOICENINJA_URL` | sí | — | URL raíz de la instancia, p. ej. `https://invoicing.co` o tu self-hosted. Se tolera un `/api/v1` final. |
| `INVOICENINJA_API_TOKEN` | sí | — | Token de API. |
| `INVOICENINJA_ENABLE_WRITES` | no | `false` | `true` habilita crear, actualizar y acciones masivas. |
| `INVOICENINJA_TIMEOUT` | no | `30` | Timeout HTTP en segundos. |
| `INVOICENINJA_VERIFY_SSL` | no | `true` | `false` para instancias con certificado autofirmado. |

### Claude Code

```bash
claude mcp add invoiceninja \
  -e INVOICENINJA_URL=https://facturacion.ejemplo.com \
  -e INVOICENINJA_API_TOKEN=tu-token \
  -- uv run --project /ruta/a/invoiceninja-mcp invoiceninja-mcp
```

### Claude Desktop

`claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "invoiceninja": {
      "command": "uv",
      "args": ["run", "--project", "/ruta/a/invoiceninja-mcp", "invoiceninja-mcp"],
      "env": {
        "INVOICENINJA_URL": "https://facturacion.ejemplo.com",
        "INVOICENINJA_API_TOKEN": "tu-token"
      }
    }
  }
}
```

### HTTP (streamable-http)

```bash
uv run invoiceninja-mcp --transport streamable-http --host 127.0.0.1 --port 8000
# endpoint: http://127.0.0.1:8000/mcp
```

El endpoint HTTP **no tiene autenticación**: cualquiera que pueda conectarse accede a tus datos de facturación. Dejalo en `127.0.0.1` o detrás de un proxy que autentique; el servidor avisa por stderr si lo ligás a otra dirección.

## Herramientas

| Herramienta | Qué hace |
|---|---|
| `invoiceninja_ping` | Verifica conexión; muestra empresa y usuario del token. |
| `invoiceninja_search` | Busca clientes, contactos, facturas y proyectos por nombre/email/número y devuelve sus IDs. |
| `invoiceninja_list_<entidad>` / `invoiceninja_get_<entidad>` | Listar (filtros, orden, paginación) y obtener un registro completo de: clients, invoices, quotes, credits, payments, recurring_invoices, products, expenses, recurring_expenses, vendors, projects, tasks, purchase_orders. |
| `invoiceninja_list_records` / `invoiceninja_get_record` | Datos de referencia: tax_rates, payment_terms, expense_categories, task_statuses, group_settings, designs, documents, bank_transactions, activities, tags, locations, subscriptions, recurring_quotes, users. |
| `invoiceninja_get_statics` | Tablas estáticas (monedas, países, tipos de pago, idiomas, zonas horarias…) para traducir IDs. |
| `invoiceninja_dashboard_totals` | Facturado, cobrado, pendiente y gastos por moneda en un período. |
| `invoiceninja_run_report` / `invoiceninja_get_report_result` | Reportes de Invoice Ninja (facturas, pagos, gastos, P&L, antigüedad de deuda, impuestos, ventas por producto…). Son asíncronos: si tardan más que `max_wait_seconds` se devuelve un `report_id` para consultarlo luego. |
| `invoiceninja_create_record` ✏️ | Crea un registro (solo con escrituras habilitadas). |
| `invoiceninja_update_record` ✏️ | Actualiza campos de un registro. |
| `invoiceninja_bulk_action` ✏️ | Archivar, restaurar, borrar, enviar por email, marcar enviada/pagada, etc. Las acciones se validan por entidad antes de llamar a la API. |

Filtros útiles en los listados: `filter` (texto libre), `client_status` (p. ej. `unpaid,overdue` en facturas), `client_id`, `status` (`active,archived,deleted`), `sort` (`date|desc`) y `extra_filters` (p. ej. `{"date_range": "2026-01-01,2026-03-31"}` o `{"balance": "gt:0"}` en clientes). Cada herramienta documenta sus filtros.

## Desarrollo

```bash
uv run pytest                 # tests unitarios y de protocolo (HTTP mockeado)
uv run pytest tests/test_read_tools.py::test_get_invoice   # un test
uv run ruff check && uv run ruff format --check
uv run mypy src tests

# smoke tests de solo lectura contra una instancia real (la demo pública sirve):
INVOICENINJA_URL=https://demo.invoiceninja.com INVOICENINJA_API_TOKEN=TOKEN uv run pytest -m live

# inspector MCP interactivo
npx @modelcontextprotocol/inspector uv run invoiceninja-mcp
```
