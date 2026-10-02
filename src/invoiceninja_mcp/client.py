"""Async HTTP client for the Invoice Ninja v5 REST API."""

from __future__ import annotations

from collections.abc import Mapping
from types import TracebackType
from typing import Any

import httpx

from invoiceninja_mcp import __version__
from invoiceninja_mcp.config import Settings

JSON = Any


class InvoiceNinjaError(Exception):
    """An API call failed. The message is safe to show to the LLM (never contains the token)."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def _clean_params(params: Mapping[str, Any] | None) -> dict[str, str | int | float]:
    cleaned: dict[str, str | int | float] = {}
    for key, value in (params or {}).items():
        if value is None:
            continue
        if isinstance(value, bool):
            cleaned[key] = "true" if value else "false"
        else:
            cleaned[key] = value
    return cleaned


def _api_message(response: httpx.Response) -> tuple[str, dict[str, Any]]:
    try:
        body = response.json()
    except ValueError:
        return response.text[:300].strip(), {}
    if isinstance(body, dict):
        errors = body.get("errors")
        return str(body.get("message") or ""), errors if isinstance(errors, dict) else {}
    return str(body)[:300], {}


def _error_for(response: httpx.Response) -> InvoiceNinjaError:
    status = response.status_code
    message, errors = _api_message(response)
    detail = f" API said: {message}" if message else ""
    if status == 401:
        text = (
            "Authentication failed (401). Check INVOICENINJA_API_TOKEN and that the token "
            f"belongs to this instance.{detail}"
        )
    elif status == 403:
        text = f"Forbidden (403): the API token's user lacks permission for this action.{detail}"
    elif status == 404:
        text = (
            "Resource not found (404). Check the id (Invoice Ninja uses hashed ids like "
            f"'Opnel5aKBz'); use a list or search tool to find valid ids.{detail}"
        )
    elif status == 409:
        text = f"Conflict (409).{detail}"
    elif status == 422:
        lines = [
            f"- {field}: {' '.join(str(m) for m in msgs) if isinstance(msgs, list) else msgs}"
            for field, msgs in errors.items()
        ]
        text = "Validation failed (422)." + detail
        if lines:
            text += "\n" + "\n".join(lines)
    elif status == 429:
        text = f"Hit the Invoice Ninja rate limit (429). Wait a minute and retry.{detail}"
    elif status >= 500:
        text = (
            f"Invoice Ninja server error ({status}). Retry later or check the server logs.{detail}"
        )
    else:
        text = f"Unexpected HTTP {status}.{detail}"
    return InvoiceNinjaError(text, status)


class InvoiceNinjaClient:
    def __init__(
        self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._settings = settings
        self._http = httpx.AsyncClient(
            base_url=settings.api_url,
            headers={
                "X-API-TOKEN": settings.api_token,
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json",
                "User-Agent": f"invoiceninja-mcp/{__version__}",
            },
            timeout=settings.timeout,
            verify=settings.verify_ssl,
            transport=transport,
        )

    async def __aenter__(self) -> InvoiceNinjaClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: JSON | None = None,
    ) -> JSON:
        url = "/" + path.lstrip("/")
        try:
            response = await self._http.request(
                method, url, params=_clean_params(params), json=json
            )
        except httpx.TimeoutException:
            raise InvoiceNinjaError(
                f"Request to {self._settings.base_url} timed out after "
                f"{self._settings.timeout:g}s. Narrow the query or raise INVOICENINJA_TIMEOUT."
            ) from None
        except httpx.HTTPError as exc:
            raise InvoiceNinjaError(
                f"Could not reach Invoice Ninja at {self._settings.base_url}: "
                f"{type(exc).__name__}. Check INVOICENINJA_URL and network access."
            ) from None
        if response.status_code >= 400:
            raise _error_for(response)
        try:
            return response.json()
        except ValueError:
            raise InvoiceNinjaError(
                f"Expected JSON from {method} {url} but got "
                f"{response.headers.get('content-type', 'unknown content')}. "
                "Check that INVOICENINJA_URL points at the Invoice Ninja root URL.",
                response.status_code,
            ) from None

    async def get(self, path: str, params: Mapping[str, Any] | None = None) -> JSON:
        return await self.request("GET", path, params=params)

    async def post(
        self, path: str, json: JSON | None = None, params: Mapping[str, Any] | None = None
    ) -> JSON:
        return await self.request("POST", path, params=params, json=json)

    async def put(
        self, path: str, json: JSON | None = None, params: Mapping[str, Any] | None = None
    ) -> JSON:
        return await self.request("PUT", path, params=params, json=json)
