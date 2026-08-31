"""Uvicorn server runner with multi-endpoint support."""

import asyncio
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

tracerite.load()  # Early load on CLI load (import server); uvicorn workers reload via log config
logger = logging.getLogger(__name__)


def run(  # noqa: PLR0913
    app: str,
    *,
    listen: str | list[str] | None = None,
    default_port: int = 8000,
    reload: bool | Path = False,
    workers: int | None = None,
    access_log: bool = True,
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
