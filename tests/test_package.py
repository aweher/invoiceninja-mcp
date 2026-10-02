import invoiceninja_mcp


def test_version_is_exposed() -> None:
    assert invoiceninja_mcp.__version__ == "0.1.0"
