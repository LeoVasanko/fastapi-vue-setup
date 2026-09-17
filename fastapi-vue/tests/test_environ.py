"""Tests for env() object binding and teleport()."""

import dataclasses
import json
import os
from collections.abc import Iterator

import msgspec
import pytest
from fastapi_vue import env, teleport
from fastapi_vue.environ import PREFIX_VARIABLE, _Env


@pytest.fixture(autouse=True)
def _clean_bindings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    env._bindings.clear()  # noqa: SLF001
    monkeypatch.setenv(PREFIX_VARIABLE, "TEST")
    yield
    env._bindings.clear()  # noqa: SLF001


class StructConfig(msgspec.Struct):
    """msgspec struct config."""

    host: str = "localhost"
    port: int = 8000


@dataclasses.dataclass
class DataclassConfig:
    """Dataclass config."""

    host: str = "localhost"
    port: int = 8000


def test_default_construction_and_identity() -> None:
    """Unset env: default-constructed; repeated binds return the same object."""
    config = env(StructConfig)
    assert config.host == "localhost"
    assert env(StructConfig) is config


def test_name_mangling() -> None:
    """Class names uppercase as-is; repeated/edge underscores normalize."""
    env(StructConfig)
    teleport()
    assert json.loads(os.environ["TEST_STRUCTCONFIG"])["port"] == 8000

    @dataclasses.dataclass
    class _my__config_:  # noqa: N801
        x: int = 0

    env(_my__config_)
    teleport()
    assert "TEST_MY_CONFIG" in os.environ


def test_name_override() -> None:
    """name= overrides the mangled class name verbatim."""
    env(DataclassConfig, name="SETTINGS")
    teleport()
    assert "TEST_SETTINGS" in os.environ


def test_name_conflict() -> None:
    """A different type with a colliding env name raises KeyError."""
    env(StructConfig)
    with pytest.raises(KeyError, match="already bound"):
        env(DataclassConfig, name="STRUCTCONFIG")


def test_reserved_names() -> None:
    """Names used by fastapi-vue itself cannot be bound, by mangle or name=."""
    with pytest.raises(KeyError, match="reserved"):
        env(DataclassConfig, name="DEV")

    @dataclasses.dataclass
    class Dev:
        x: int = 0

    with pytest.raises(KeyError, match="reserved"):
        env(Dev)


def test_unsupported_type() -> None:
    """Only dataclasses and msgspec.Structs can be bound."""
    with pytest.raises(TypeError, match=r"dataclass or msgspec\.Struct"):
        env(dict)


def test_struct_teleport_and_decode() -> None:
    """A mutated struct teleports; a fresh registry decodes it (worker view)."""
    config = env(StructConfig)
    config.port = 9000
    teleport()
    decoded = _Env()(StructConfig)
    assert decoded == config
    assert decoded is not config


def test_dataclass_teleport_and_decode() -> None:
    """Dataclasses round-trip through the environment via stdlib json."""
    config = env(DataclassConfig)
    config.host = "example.com"
    teleport()
    assert _Env()(DataclassConfig) == config


def test_decode_on_bind_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """An already-set variable is decoded at binding time."""
    monkeypatch.setenv("TEST_STRUCTCONFIG", '{"host": "example.com", "port": 1}')
    assert env(StructConfig).host == "example.com"


def test_teleport_without_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """teleport() with bindings but no FASTAPI_VUE prefix fails loudly."""
    monkeypatch.delenv(PREFIX_VARIABLE)
    env(StructConfig)
    with pytest.raises(RuntimeError, match=PREFIX_VARIABLE):
        teleport()


def test_teleport_noop_without_bindings() -> None:
    """No bindings: teleport() needs no prefix and does nothing."""
    teleport()
