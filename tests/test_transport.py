"""Tests for the transport layer's server metadata.

The version advertised during the MCP `initialize` handshake is read from
the installed distribution so it can't drift from `pyproject.toml`.
"""

from importlib.metadata import PackageNotFoundError, version

from mcp.server import Server

from ashby import transport


def test_server_version_matches_installed_distribution():
    assert transport.server_version() == version("mcp-ashby-connector")
    assert transport.server_version() != transport._DEV_VERSION


def test_server_version_falls_back_when_not_installed(monkeypatch):
    def _missing(name: str) -> str:
        raise PackageNotFoundError(name)

    monkeypatch.setattr(transport, "version", _missing)
    assert transport.server_version() == "0.0.0+dev"


def test_init_options_advertise_name_and_version():
    opts = transport._init_options(Server("test"))
    assert opts.server_name == "ashby-mcp"
    assert opts.server_version == transport.server_version()
