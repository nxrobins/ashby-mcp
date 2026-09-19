"""Runtime hardening policy — read from the environment on every call.

The stdio transport runs on the user's own machine, so it gets the
permissive defaults a local tool should have. The HTTP transport is a
shared deployment reachable by every bearer-token holder (and by any
prompt injection carried in candidate data), so it defaults to the
stricter side and the operator opts back in explicitly.

  MCP_TRANSPORT      "stdio" (default) or "http" — chosen in server.run().
  ASHBY_READ_ONLY    truthy ("1", "true", "yes", "on") → every tool that
                     writes to Ashby is hidden from tools/list and rejected
                     by the dispatcher.
  ASHBY_UPLOAD_DIR   the only directory the upload tools may read files
                     from. Over HTTP the upload tools are disabled until
                     this is set; over stdio it is optional and merely
                     confines paths when present.

Nothing here is cached: tests flip these with monkeypatch, and there is
no startup snapshot that could drift from the environment.
"""

import os

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def env_flag(name: str) -> bool:
    """True when the env var holds a truthy value (case-insensitive)."""
    return (os.getenv(name) or "").strip().lower() in _TRUTHY


def transport() -> str:
    """The MCP transport selected by MCP_TRANSPORT ("stdio" unless "http")."""
    return (os.getenv("MCP_TRANSPORT") or "stdio").strip().lower()


def is_http_transport() -> bool:
    return transport() == "http"


def read_only_mode() -> bool:
    """ASHBY_READ_ONLY — hide and reject every tool that writes to Ashby."""
    return env_flag("ASHBY_READ_ONLY")


def upload_dir() -> str | None:
    """ASHBY_UPLOAD_DIR, or None when unset/blank."""
    value = (os.getenv("ASHBY_UPLOAD_DIR") or "").strip()
    return value or None


def uploads_enabled() -> bool:
    """Whether the upload tools may run at all.

    Over stdio they read the user's own files (the intended design). Over
    HTTP an unconfined `file_path` is an arbitrary-file-read of the server
    container — /proc/self/environ holds the Ashby key and the bearer
    token — so they stay off until ASHBY_UPLOAD_DIR confines them.
    """
    return upload_dir() is not None or not is_http_transport()


def resolve_upload_path(path: str) -> str:
    """Return the path an upload tool may open, or raise PermissionError.

    Without ASHBY_UPLOAD_DIR the path is used as-is over stdio and refused
    over HTTP. With it, relative paths resolve inside the directory,
    symlinks and `..` are resolved first (os.path.realpath), and anything
    that lands outside the directory is refused.
    """
    base = upload_dir()
    if base is None:
        if is_http_transport():
            raise PermissionError(
                "file uploads are disabled over the HTTP transport; set ASHBY_UPLOAD_DIR "
                "to the directory the server may upload files from to enable them"
            )
        return path

    root = os.path.realpath(base)
    target = os.path.realpath(os.path.join(root, path))
    try:
        inside = os.path.commonpath([root, target]) == root
    except ValueError:  # different drives on Windows
        inside = False
    if not inside:
        raise PermissionError(
            f"file_path must stay inside ASHBY_UPLOAD_DIR ({base}); refusing {path!r}"
        )
    return target
