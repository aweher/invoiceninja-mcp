import pytest

from invoiceninja_mcp.config import ConfigError, Settings

BASE = {"INVOICENINJA_URL": "https://ninja.example.com", "INVOICENINJA_API_TOKEN": "secret"}


def test_minimal_env_uses_defaults() -> None:
    s = Settings.from_env(BASE)
    assert s.base_url == "https://ninja.example.com"
    assert s.api_url == "https://ninja.example.com/api/v1"
    assert s.api_token == "secret"
    assert s.enable_writes is False
    assert s.timeout == 30.0
    assert s.verify_ssl is True


@pytest.mark.parametrize(
    "raw",
    [
        "https://ninja.example.com/",
        "https://ninja.example.com/api/v1",
        "https://ninja.example.com/api/v1/",
        "  https://ninja.example.com  ",
    ],
)
def test_url_is_normalized(raw: str) -> None:
    s = Settings.from_env({**BASE, "INVOICENINJA_URL": raw})
    assert s.base_url == "https://ninja.example.com"


def test_url_keeps_subpath() -> None:
    s = Settings.from_env({**BASE, "INVOICENINJA_URL": "https://example.com/ninja/"})
    assert s.api_url == "https://example.com/ninja/api/v1"


@pytest.mark.parametrize("missing", ["INVOICENINJA_URL", "INVOICENINJA_API_TOKEN"])
def test_missing_required_var(missing: str) -> None:
    env = {k: v for k, v in BASE.items() if k != missing}
    with pytest.raises(ConfigError, match=missing):
        Settings.from_env(env)


def test_blank_token_is_missing() -> None:
    with pytest.raises(ConfigError, match="INVOICENINJA_API_TOKEN"):
        Settings.from_env({**BASE, "INVOICENINJA_API_TOKEN": "   "})


def test_url_requires_http_scheme() -> None:
    with pytest.raises(ConfigError, match="http"):
        Settings.from_env({**BASE, "INVOICENINJA_URL": "ninja.example.com"})


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("true", True),
        ("1", True),
        ("YES", True),
        ("on", True),
        ("false", False),
        ("0", False),
        ("no", False),
        ("", False),
    ],
)
def test_enable_writes_parsing(raw: str, expected: bool) -> None:
    s = Settings.from_env({**BASE, "INVOICENINJA_ENABLE_WRITES": raw})
    assert s.enable_writes is expected


def test_invalid_bool_is_rejected() -> None:
    with pytest.raises(ConfigError, match="INVOICENINJA_VERIFY_SSL"):
        Settings.from_env({**BASE, "INVOICENINJA_VERIFY_SSL": "maybe"})


def test_timeout_parsing() -> None:
    assert Settings.from_env({**BASE, "INVOICENINJA_TIMEOUT": "12.5"}).timeout == 12.5


@pytest.mark.parametrize("raw", ["abc", "0", "-3"])
def test_invalid_timeout(raw: str) -> None:
    with pytest.raises(ConfigError, match="INVOICENINJA_TIMEOUT"):
        Settings.from_env({**BASE, "INVOICENINJA_TIMEOUT": raw})


def test_repr_hides_token() -> None:
    assert "secret" not in repr(Settings.from_env(BASE))
