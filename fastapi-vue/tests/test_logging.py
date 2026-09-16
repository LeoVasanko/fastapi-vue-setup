"""Tests for fastapi_vue.logging.patch_log_config overlay behavior."""

import logging.config

from fastapi_vue.logging import patch_log_config


def test_empty_dict_overlays_uvicorn_defaults() -> None:
    """An empty dict is a partial config: merged over uvicorn's defaults."""
    config = patch_log_config({})
    assert config["version"] == 1
    assert config["disable_existing_loggers"] is False
    assert config["root"]["handlers"] == ["default"]
    assert "uvicorn" in config["loggers"]
    logging.config.dictConfig(config)  # must be a valid, complete config


def test_partial_logger_customization() -> None:
    """The documented use case: only the customization, no boilerplate."""
    config = patch_log_config({"loggers": {"kanta": {"level": "DEBUG"}}})
    assert config["loggers"]["kanta"] == {"level": "DEBUG"}
    assert config["loggers"]["uvicorn"]["handlers"] == ["default"]
    assert config["loggers"]["watchfiles.main"]["level"] == "WARNING"
    logging.config.dictConfig(config)
    assert logging.getLogger("kanta").level == logging.DEBUG


def test_overlay_root_level_wins() -> None:
    """User-supplied root level is kept; our handler wiring still applies."""
    config = patch_log_config({"root": {"level": "ERROR"}})
    assert config["root"]["level"] == "ERROR"
    assert config["root"]["handlers"] == ["default"]
    logging.config.dictConfig(config)
    assert logging.getLogger().level == logging.ERROR


def test_overlay_formatter_customization_keeps_stock_siblings() -> None:
    """A user formatter replaces ours; the access formatter still works."""
    config = patch_log_config({"formatters": {"default": {"fmt": "%(name)s %(message)s"}}})
    assert config["formatters"]["default"] == {
        "()": "uvicorn.logging.DefaultFormatter",  # stock class, user's fmt
        "fmt": "%(name)s %(message)s",
        "use_colors": None,
    }
    assert "access" in config["formatters"]
    logging.config.dictConfig(config)


def test_full_config_used_as_is() -> None:
    """A dict with version is complete: no uvicorn loggers appear."""
    config = patch_log_config({"version": 1})
    assert "uvicorn" not in config.get("loggers", {})
    # No "default" handler exists, so root must not reference one.
    assert "handlers" not in config["root"]
    logging.config.dictConfig(config)


def test_non_dict_passes_through() -> None:
    """Non-dict configs (e.g. an ini file path) are returned untouched."""
    assert patch_log_config("logging.ini") == "logging.ini"
