"""Uvicorn server runner with multi-endpoint support."""

import asyncio
import importlib.metadata
import logging
import os
from contextlib import suppress
from pathlib import Path
from typing import Any

import tracerite
import uvicorn
from uvicorn import Config, Server

from .hostutil import parse_endpoints
from .logging import install_access_log, patch_log_config
from .startupbox import print_box

tracerite.load()  # Early load on CLI load (import server); uvicorn workers reload via log config
logger = logging.getLogger(__name__)

_WILDCARD_HOSTS = frozenset({"0.0.0.0", "::"})  # noqa: S104


def _connect_url(endpoints: list[dict]) -> str:
    """Return a URL the user can connect to for the first TCP endpoint.

    Wildcard binds (0.0.0.0, ::) are shown as localhost, as that is the
    address a user can actually open. Returns "" for unix-socket-only setups.
    """
    for endpoint in endpoints:
        host = endpoint.get("host")
        if host is None:
            continue
        if host in _WILDCARD_HOSTS:
            host = "localhost"
        elif ":" in host:  # IPv6 literal
            host = f"[{host}]"
        return f"http://{host}:{endpoint['port']}"
    return ""


def _print_startup_box(template: str, app: str, endpoints: list[dict]) -> None:
    """Format the startup box template and print it.

    Available fields: ``{module}`` (top-level package of the app path),
    ``{name}`` (module with spaces instead of underscores), ``{Name}``
    (also capitalized), ``{version}`` (from installed package metadata,
    "dev" when not installed) and ``{url}``.
    """
    module = app.split(":", 1)[0].split(".", 1)[0]
    name = module.replace("_", " ")
    try:
        version = importlib.metadata.version(module)
    except importlib.metadata.PackageNotFoundError:
        version = ""
    values = {
        "module": module,
        "name": name,
        "Name": name.title(),
        "version": version,
        "url": _connect_url(endpoints),
    }
    print_box(template.format_map(values))


def run(  # noqa: PLR0913
    app: str,
    *,
    listen: str | list[str] | None = None,
    default_port: int = 8000,
    reload: bool | Path = False,
    workers: int | None = None,
    access_log: bool = True,
    startup_box: str | None = "{Name} {version}\n{url}",
    log_config: Any = uvicorn.config.LOGGING_CONFIG,  # noqa: ANN401
    **uvicorn_config: Any,  # noqa: ANN401
) -> None:
    """Run uvicorn server(s) for the given app.

    Args:
        app: The ASGI application path (e.g., "myapp.main:app")
        listen: Endpoint string(s) (see parse_endpoint for formats).
        default_port: Port to use when not specified in listen args.
        reload: Enable auto-reload. If a Path is given, reload watches that
            directory. True enables reload without setting a reload directory.
            False disables reload and clears any reload_dirs.
        workers: Number of worker processes (requires uvicorn.run, single endpoint only).
        access_log: Enable our colored HTTP/WebSocket access logging middleware
            (uvicorn's own access logging is always bypassed).
        startup_box: Template for the startup box printed to stderr before
            serving (see _print_startup_box for fields), None to not print it.
        log_config: Logging config passed to uvicorn. Dict configs are patched
            best-effort (see fastapi_vue.logging.patch_log_config): tracerite
            loading and WebSocket chatter filtering are always installed, and
            when access_log is enabled the access formatting is rewired too.
        **uvicorn_config: Additional uvicorn config options (overrides all other settings).

    """
    endpoints = parse_endpoints(listen, default_port)
    if not endpoints:
        msg = "No endpoints to serve; check listen configuration"
        raise ValueError(msg)

    if startup_box:
        _print_startup_box(startup_box, app, endpoints)

    if isinstance(reload, Path):
        uvicorn_config["reload_dirs"] = [str(reload)]
    elif not reload:
        uvicorn_config.pop("reload_dirs", None)

    if access_log:
        install_access_log()
    uvicorn_config["access_log"] = False  # We always bypass uvicorn's own access logging
    uvicorn_config["log_config"] = patch_log_config(log_config, access_log=access_log)

    conf: dict[str, object] = {"app": app, "reload": bool(reload), "workers": workers}
    proxy = os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1,::1")
    if proxy:
        conf["proxy_headers"] = True
        conf["forwarded_allow_ips"] = proxy
    conf.update(uvicorn_config)

    with suppress(KeyboardInterrupt, asyncio.CancelledError):
        if reload or workers:
            serve_multiprocess(endpoints, **conf)
        else:
            asyncio.run(serve(endpoints, **conf))


async def serve(endpoints: list[dict], **kwargs: Any) -> None:  # noqa: ANN401
    """Serve the given endpoints in current process/loop. Does not spawn extra processes."""
    forbidden = {"reload", "workers"} & {k for k, v in kwargs.items() if v}
    if forbidden:
        logger.warning(
            "Options %s have no effect in simple mode (multiple endpoints)",
            ", ".join(sorted(forbidden)),
        )
    await asyncio.gather(*(Server(Config(**kwargs, **ep)).serve() for ep in endpoints))


def serve_multiprocess(endpoints: list[dict], **kwargs: Any) -> None:  # noqa: ANN401
    """Serve using uvicorn.run() for reload/workers support. Only first endpoint is used."""
    if len(endpoints) > 1:
        eps = [ep["uds"] if "uds" in ep else f"{ep['host']}:{ep['port']}" for ep in endpoints]
        logger.warning(
            "Current mode supports only one endpoint. Listening: %s, skipped: %s",
            eps[0],
            " ".join(eps[1:]),
        )
    uvicorn.run(**kwargs, **endpoints[0])
