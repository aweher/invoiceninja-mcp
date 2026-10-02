from collections.abc import AsyncIterator

import httpx
import pytest
import respx

from invoiceninja_mcp.client import InvoiceNinjaClient, InvoiceNinjaError
from invoiceninja_mcp.config import Settings

API = "https://ninja.example.com/api/v1"


@pytest.fixture
async def client() -> AsyncIterator[InvoiceNinjaClient]:
    settings = Settings(base_url="https://ninja.example.com", api_token="tok-123")
    async with InvoiceNinjaClient(settings) as c:
        yield c


@respx.mock
async def test_get_sends_auth_headers_and_returns_json(client: InvoiceNinjaClient) -> None:
    route = respx.get(f"{API}/ping").mock(
        return_value=httpx.Response(200, json={"company_name": "Acme"})
    )
    assert await client.get("/ping") == {"company_name": "Acme"}
    req = route.calls.last.request
    assert req.headers["X-API-TOKEN"] == "tok-123"
    assert req.headers["X-Requested-With"] == "XMLHttpRequest"
    assert req.headers["Accept"] == "application/json"


@respx.mock
async def test_get_drops_none_params_and_serializes_bools(client: InvoiceNinjaClient) -> None:
    route = respx.get(f"{API}/invoices").mock(return_value=httpx.Response(200, json={"data": []}))
    await client.get("invoices", params={"page": 2, "filter": None, "is_deleted": False})
    params = route.calls.last.request.url.params
    assert params["page"] == "2"
    assert params["is_deleted"] == "false"
    assert "filter" not in params


@respx.mock
async def test_post_and_put_send_json(client: InvoiceNinjaClient) -> None:
    post = respx.post(f"{API}/clients").mock(return_value=httpx.Response(200, json={"data": {}}))
    put = respx.put(f"{API}/clients/abc").mock(return_value=httpx.Response(200, json={"data": {}}))
    await client.post("/clients", json={"name": "Bob"})
    await client.put("/clients/abc", json={"name": "Rob"})
    assert post.calls.last.request.content == b'{"name":"Bob"}'
    assert put.calls.last.request.content == b'{"name":"Rob"}'


@respx.mock
async def test_post_passes_query_params(client: InvoiceNinjaClient) -> None:
    route = respx.post(f"{API}/charts/totals").mock(return_value=httpx.Response(200, json={}))
    await client.post("/charts/totals", json={}, params={"rows": 5})
    assert route.calls.last.request.url.params["rows"] == "5"


@pytest.mark.parametrize(
    ("status", "body", "fragment"),
    [
        (401, {"message": "Invalid token"}, "INVOICENINJA_API_TOKEN"),
        (403, {"message": "Forbidden"}, "permission"),
        (404, {"message": "Not found"}, "not found"),
        (429, {"message": "Too Many Attempts."}, "rate limit"),
        (500, {"message": "Server Error"}, "server error"),
    ],
)
@respx.mock
async def test_http_errors_are_mapped(
    client: InvoiceNinjaClient, status: int, body: dict[str, str], fragment: str
) -> None:
    respx.get(f"{API}/invoices/xyz").mock(return_value=httpx.Response(status, json=body))
    with pytest.raises(InvoiceNinjaError) as exc:
        await client.get("/invoices/xyz")
    assert exc.value.status == status
    assert fragment.lower() in str(exc.value).lower()
    assert "tok-123" not in str(exc.value)


@respx.mock
async def test_422_lists_field_errors(client: InvoiceNinjaClient) -> None:
    body = {
        "message": "The given data was invalid.",
        "errors": {"client_id": ["The client id field is required."], "date": ["Bad date."]},
    }
    respx.post(f"{API}/invoices").mock(return_value=httpx.Response(422, json=body))
    with pytest.raises(InvoiceNinjaError) as exc:
        await client.post("/invoices", json={})
    msg = str(exc.value)
    assert "client_id: The client id field is required." in msg
    assert "date: Bad date." in msg


@respx.mock
async def test_non_json_success_raises(client: InvoiceNinjaClient) -> None:
    respx.get(f"{API}/ping").mock(return_value=httpx.Response(200, text="<html>login</html>"))
    with pytest.raises(InvoiceNinjaError, match="JSON"):
        await client.get("/ping")


@respx.mock
async def test_network_error_is_mapped(client: InvoiceNinjaClient) -> None:
    respx.get(f"{API}/ping").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(InvoiceNinjaError, match="Could not reach"):
        await client.get("/ping")


@respx.mock
async def test_timeout_is_mapped(client: InvoiceNinjaClient) -> None:
    respx.get(f"{API}/ping").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(InvoiceNinjaError, match="timed out"):
        await client.get("/ping")
