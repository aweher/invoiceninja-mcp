"""Configuration loaded from environment variables."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off", ""}


class ConfigError(ValueError):
    """Raised when the environment does not describe a usable configuration."""


def _parse_bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ConfigError(f"{name} must be a boolean (true/false), got {raw!r}")


def _normalize_url(raw: str) -> str:
    url = raw.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        raise ConfigError(
            f"INVOICENINJA_URL must start with http:// or https://, got {raw.strip()!r}"
        )
    if url.endswith("/api/v1"):
        url = url[: -len("/api/v1")]
    return url


@dataclass(frozen=True)
class Settings:
    base_url: str
    api_token: str = field(repr=False)
    enable_writes: bool = False
    timeout: float = 30.0
    verify_ssl: bool = True

    @property
    def api_url(self) -> str:
        return f"{self.base_url}/api/v1"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env

        url = (env.get("INVOICENINJA_URL") or "").strip()
        if not url:
            raise ConfigError(
                "INVOICENINJA_URL is not set (e.g. https://invoicing.co or your self-hosted URL)"
            )
        token = (env.get("INVOICENINJA_API_TOKEN") or "").strip()
        if not token:
            raise ConfigError(
                "INVOICENINJA_API_TOKEN is not set "
                "(create one in Settings > Account Management > API Tokens)"
            )

        raw_timeout = env.get("INVOICENINJA_TIMEOUT", "30")
        try:
            timeout = float(raw_timeout)
        except ValueError:
            raise ConfigError(
                f"INVOICENINJA_TIMEOUT must be a number of seconds, got {raw_timeout!r}"
            ) from None
        if timeout <= 0:
            raise ConfigError(f"INVOICENINJA_TIMEOUT must be positive, got {raw_timeout!r}")

        return cls(
            base_url=_normalize_url(url),
            api_token=token,
            enable_writes=_parse_bool(env, "INVOICENINJA_ENABLE_WRITES", False),
            timeout=timeout,
            verify_ssl=_parse_bool(env, "INVOICENINJA_VERIFY_SSL", True),
        )
