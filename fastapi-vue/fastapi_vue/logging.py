"""Access log formatting, adapted from uvicorn's logging module.

Unlike uvicorn's AccessFormatter, the colored fields (``client``, ``status``,
``method``, ``host``, ``path``, ``extra``, ``timing``) are supplied by the
access log middleware via ``extra=``.  When colors are disabled the ANSI
escape codes are stripped from the assembled output so the same formatting
code path produces plain text.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Callable
from contextlib import suppress
from copy import deepcopy
from typing import Any, Literal

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")

ACCESS_LOG_FMT = "%(client)s %(status)s %(method)s %(host)s%(path)s %(extra)s%(timing)s"


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text)


LogConfigPatch = Callable[[dict[str, Any]], None]

_LOG_CONFIG_PATCHES: list[LogConfigPatch] = []


def log_config_patch(patch: LogConfigPatch) -> LogConfigPatch:
    """Register a best-effort log config patch (applied by patch_log_config)."""
    _LOG_CONFIG_PATCHES.append(patch)
    return patch


def patch_log_config(log_config: Any) -> Any:  # noqa: ANN401
    """Apply registered patches to a uvicorn log_config.

    Users presumably base their config on uvicorn's default dict, but any
    shape is tolerated: each patch is applied on a best-effort basis and
    silently skipped when the config does not have the expected structure.
    Non-dict configs (e.g. an ini file path) pass through untouched.
    """
    if not isinstance(log_config, dict):
        return log_config
    config = deepcopy(log_config)
    for patch in _LOG_CONFIG_PATCHES:
        with suppress(Exception):
            patch(config)
    return config


class WebSocketChatterFilter(logging.Filter):
    """Drop stock uvicorn WebSocket handshake/chatter records.

    Stock uvicorn logs WS handshakes (``'%s - "WebSocket %s" ...'``) and the
    websockets library's "connection open/closed" chatter to ``uvicorn.error``,
    ungated by ``access_log``.  Our middleware logs WebSockets itself.
    """

    _PREFIXES = ('%s - "WebSocket ', "connection open", "connection closed", "connection rejected")

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.msg
        if not isinstance(msg, str):
            return True
        return not msg.startswith(self._PREFIXES)


class AccessFormatter(logging.Formatter):
    """Formatter for the combined HTTP/WebSocket access log.

    Instantiation installs the middleware patch: ``dictConfig`` builds this
    formatter while uvicorn applies ``log_config``, which happens before the
    app is loaded — including in reload/worker subprocesses that re-import the
    config without calling ``fastapi_vue.server.run()`` again.
    """

    def __init__(
        self,
        fmt: str | None = None,
        datefmt: str | None = None,
        style: Literal["%", "{", "$"] = "%",
        use_colors: bool | None = None,
    ):
        install_access_log()
        if use_colors in (True, False):
            self.use_colors = use_colors
        else:
            self.use_colors = sys.stdout.isatty()
        super().__init__(fmt=fmt, datefmt=datefmt, style=style)

    def formatMessage(self, record: logging.LogRecord) -> str:
        formatted = super().formatMessage(record)
        if not self.use_colors:
            formatted = strip_ansi(formatted)
        return formatted


def install_access_log() -> None:
    """Wrap apps loaded by uvicorn with AccessLogMiddleware (idempotent)."""
    from uvicorn.config import Config

    from .accesslog import AccessLogMiddleware

    if getattr(Config, "_fastapi_vue_accesslog", False):
        return
    Config._fastapi_vue_accesslog = True  # type: ignore[attr-defined]

    if hasattr(Config, "load_app"):  # uvicorn < 0.40
        original_load_app = Config.load_app

        def load_app(self):  # noqa: ANN001, ANN202
            app = original_load_app(self)
            return app if isinstance(app, AccessLogMiddleware) else AccessLogMiddleware(app)

        Config.load_app = load_app  # type: ignore[method-assign]
    else:
        original_load = Config.load

        def load(self):  # noqa: ANN001, ANN202
            original_load(self)
            if not isinstance(self.loaded_app, AccessLogMiddleware):
                self.loaded_app = AccessLogMiddleware(self.loaded_app)

        Config.load = load  # type: ignore[method-assign]


@log_config_patch
def _patch_access_log(config: dict[str, Any]) -> None:
    """Rewire a uvicorn log_config dict for our colored access logging.

    Logs to a private ``fastapi_vue.access`` logger: uvicorn's protocol-level
    access logging is driven by ``uvicorn.access.hasHandlers()``, so we must
    not attach handlers to that logger (``access_log=False`` strips them).
    """
    formatters = config.get("formatters")
    if isinstance(formatters, dict):
        formatters["access"] = {
            "()": "fastapi_vue.logging.AccessFormatter",
            "fmt": ACCESS_LOG_FMT,
            "use_colors": None,
        }

    handlers = config.get("handlers")
    if not isinstance(handlers, dict):
        return

    loggers = config.setdefault("loggers", {})
    if isinstance(loggers, dict) and "access" in handlers:
        loggers["fastapi_vue.access"] = {
            "handlers": ["access"],
            "level": "INFO",
            "propagate": False,
        }

    default = handlers.get("default")
    if isinstance(default, dict):
        filters = config.setdefault("filters", {})
        if isinstance(filters, dict):
            filters["ws_chatter"] = {"()": "fastapi_vue.logging.WebSocketChatterFilter"}
            handler_filters = default.setdefault("filters", [])
            if isinstance(handler_filters, list) and "ws_chatter" not in handler_filters:
                handler_filters.append("ws_chatter")
