"""Uvicorn server runner with multi-endpoint support."""

import asyncio
import importlib.metadata
import logging
import os
import socket
from contextlib import suppress
from pathlib import Path
from typing import Any

import tracerite
import uvicorn
from uvicorn import Config, Server
from uvicorn.main import STARTUP_FAILURE
from uvicorn.supervisors import ChangeReload, Multiprocess

from .environ import env, teleport
from .hostutil import parse_endpoints
from .logging import (
    install_access_log,
    patch_lifespan_logging,
    patch_log_config,
    patch_server_error_middleware,
    use_color,
)
from .startupbox import print_box

tracerite.load()  # Early load on CLI load (import server); uvicorn workers reload via log config

# Install force color to aid tracerite and any external software to use full color when available
# Define NO_COLOR or FORCE_COLOR beforehand to avoid this
if "FORCE_COLOR" not in os.environ and use_color():
    os.environ["FORCE_COLOR"] = "3"

logger = logging.getLogger(__name__)

_WILDCARD_HOSTS = frozenset({"0.0.0.0", "::"})  # noqa: S104
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1"})


def _bind_hosts(host: str) -> list[str]:
    """Addresses bound for a configured host; localhost binds both loopbacks."""
    return sorted(_LOOPBACK_HOSTS) if host == "localhost" else [host]


def _connect_url(endpoints: list[dict]) -> str:
    """Return a URL the user can connect to for the first TCP endpoint.

    When running under the devserver (<PREFIX>_VITE_URL is set), the vite
    devserver URL is shown instead, as that is where the page is served.
    Wildcard binds (0.0.0.0, ::) are shown as localhost, as that is the
    address a user can actually open. Unix-socket-only setups show plain
    http://localhost (the typical reverse-proxy target).
    """
    if vite_url := env.vite_url:
        return vite_url
    for endpoint in endpoints:
        host = endpoint.get("host")
        if host is None:
            continue
        if host in _WILDCARD_HOSTS:
            host = "localhost"
        elif ":" in host:  # IPv6 literal
            host = f"[{host}]"
        return f"http://{host}:{endpoint['port']}"
    return "http://localhost"


def _listen_addresses(endpoints: list[dict]) -> str:
    """Return space-separated listen addresses as bound (host:port or uds path).

    localhost is expanded to both loopbacks, matching the actual binds.
    """
    parts = []
    for ep in endpoints:
        if "uds" in ep:
            parts.append(ep["uds"])
            continue
        for addr in _bind_hosts(ep["host"]):
            shown = f"[{addr}]" if ":" in addr else addr  # bracket IPv6 literals
            parts.append(f"{shown}:{ep['port']}")
    return " ".join(dict.fromkeys(parts))


def print_startup_box(template: str, app: str, endpoints: list[dict]) -> None:
    """Format the startup box template and print it.

    Available fields: ``{module}`` (top-level package of the app path),
    ``{name}`` (module with spaces instead of underscores), ``{Name}``
    (also capitalized), ``{version}`` (from installed package metadata,
    "dev" when not installed), ``{listen}`` (space-separated listen
    addresses as bound, localhost expanded to both loopbacks) and ``{url}``
    (vite devserver URL when set, else the first connectable backend URL).
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
        "listen": _listen_addresses(endpoints),
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
    startup_box: str | None = "{Name} {version} @ {listen}\n{url}",
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
            serving (see print_startup_box for fields), None to not print it.
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

    teleport()  # Serialize bound objects before spawning workers

    if startup_box:
        print_startup_box(startup_box, app, endpoints)

    if isinstance(reload, Path):
        uvicorn_config["reload_dirs"] = [str(reload)]
    elif not reload:
        uvicorn_config.pop("reload_dirs", None)

    if access_log:
        install_access_log()
    patch_lifespan_logging()
    patch_server_error_middleware()
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


def _bind_sockets(endpoints: list[dict]) -> list[socket.socket]:
    """Bind sockets for all endpoints, expanding localhost to both loopbacks.

    localhost is bound as 127.0.0.1 and ::1 explicitly, so resolver quirks
    (notably Windows resolving localhost to ::1 only) cannot make the server
    unreachable. Addresses that cannot be bound (e.g. IPv6 unavailable) are
    skipped with a warning; exits only if nothing could be bound.
    """
    sockets: list[socket.socket] = []
    seen: set = set()
    for ep in endpoints:
        if "uds" in ep:
            uds = ep["uds"]
            if uds in seen:
                continue
            seen.add(uds)
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                sock.bind(uds)
                Path(uds).chmod(0o666)
            except OSError as e:
                logger.warning("Could not bind unix socket %s: %s", uds, e)
                sock.close()
                continue
            sock.set_inheritable(True)
            sockets.append(sock)
            continue

        host, port = ep["host"], ep["port"]
        for addr in _bind_hosts(host):
            if (addr, port) in seen:
                continue
            seen.add((addr, port))
            family = socket.AF_INET6 if ":" in addr else socket.AF_INET
            sock = socket.socket(family, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if family == socket.AF_INET6:
                with suppress(OSError):
                    sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            try:
                sock.bind((addr, port))
            except OSError as e:
                logger.warning("Could not bind %s:%d: %s", addr, port, e)
                sock.close()
                continue
            sock.set_inheritable(True)
            sockets.append(sock)

    if not sockets:
        logger.error("Could not bind any endpoint")
        raise SystemExit(STARTUP_FAILURE)
    return sockets


def _remove_uds_files(endpoints: list[dict]) -> None:
    """Remove unix socket files we created (mirrors uvicorn.run cleanup)."""
    for ep in endpoints:
        if "uds" in ep:
            Path(ep["uds"]).unlink(missing_ok=True)


async def serve(endpoints: list[dict], **kwargs: Any) -> None:  # noqa: ANN401
    """Serve the given endpoints in current process/loop. Does not spawn extra processes."""
    forbidden = {"reload", "workers"} & {k for k, v in kwargs.items() if v}
    if forbidden:
        logger.warning(
            "Options %s have no effect in simple mode (multiple endpoints)",
            ", ".join(sorted(forbidden)),
        )
    try:
        await Server(Config(**kwargs)).serve(sockets=_bind_sockets(endpoints))
    finally:
        _remove_uds_files(endpoints)


def serve_multiprocess(endpoints: list[dict], **kwargs: Any) -> None:  # noqa: ANN401
    """Serve using uvicorn supervisors for reload/workers support."""
    config = Config(**kwargs)
    server = Server(config)
    sockets = _bind_sockets(endpoints)
    try:
        if config.should_reload:
            ChangeReload(config, target=server.run, sockets=sockets).run()
        else:
            Multiprocess(config, sockets=sockets).run()
    finally:
        _remove_uds_files(endpoints)
