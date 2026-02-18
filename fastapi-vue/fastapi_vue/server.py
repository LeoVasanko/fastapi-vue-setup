import asyncio
import logging
import os
from contextlib import suppress

import uvicorn
from uvicorn import Config, Server

from .hostutil import parse_endpoints

logger = logging.getLogger(__name__)


def run(
    app: str,
    *,
    listen: str | list[str] | None = None,
    default_port: int = 8000,
    reload: bool = False,
    workers: int | None = None,
    **uvicorn_config,
):
    """Run uvicorn server(s) for the given app.

    Args:
        app: The ASGI application path (e.g., "myapp.main:app")
        listen: Endpoint string(s) (see parse_endpoint for formats).
        default_port: Port to use when not specified in listen args.
        reload: Enable auto-reload (requires uvicorn.run, single endpoint only).
        workers: Number of worker processes (requires uvicorn.run, single endpoint only).
        **uvicorn_config: Additional uvicorn config options (overrides all other settings).
    """
    endpoints = parse_endpoints(listen, default_port)
    if not endpoints:
        raise ValueError("No endpoints to serve; check listen configuration")

    conf: dict[str, object] = {"app": app, "reload": reload, "workers": workers}
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


async def serve(endpoints: list[dict], **kwargs) -> None:
    """Serve the given endpoints in current process/loop. Does not spawn extra processes."""
    forbidden = {"reload", "workers"} & {k for k, v in kwargs.items() if v}
    if forbidden:
        logger.warning(
            "Options %s have no effect in simple mode (multiple endpoints)",
            ", ".join(sorted(forbidden)),
        )
    await asyncio.gather(*(Server(Config(**kwargs, **ep)).serve() for ep in endpoints))


def serve_multiprocess(endpoints: list[dict], **kwargs) -> None:
    """Serve using uvicorn.run() for reload/workers support. Only first endpoint is used."""
    if len(endpoints) > 1:
        eps = [
            ep["uds"] if "uds" in ep else f"{ep['host']}:{ep['port']}"
            for ep in endpoints
        ]
        logger.warning(
            "Current mode supports only one endpoint. Listening: %s, skipped: %s",
            eps[0],
            " ".join(eps[1:]),
        )
    uvicorn.run(**kwargs, **endpoints[0])
