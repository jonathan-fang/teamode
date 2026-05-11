"""Tests for app.config environment-variable loader."""

import importlib
import sys

import pytest


def _reload_config() -> object:
    """Force a fresh import of app.config, bypassing the module cache."""
    sys.modules.pop("app.config", None)
    return importlib.import_module("app.config")


def test_happy_path_default_db(monkeypatch: pytest.MonkeyPatch) -> None:
    """Token present, TEAMODE_DB_PATH unset → default db path applied."""
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token-abcd")
    monkeypatch.delenv("TEAMODE_DB_PATH", raising=False)

    cfg = _reload_config()

    assert cfg.DISCORD_BOT_TOKEN == "test-token-abcd"  # type: ignore[attr-defined]
    assert cfg.TEAMODE_DB_PATH == "./sessions.db"  # type: ignore[attr-defined]


def test_happy_path_custom_db(monkeypatch: pytest.MonkeyPatch) -> None:
    """Token present, TEAMODE_DB_PATH set → custom path is used."""
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token-wxyz")
    monkeypatch.setenv("TEAMODE_DB_PATH", "/tmp/test.db")

    cfg = _reload_config()

    assert cfg.TEAMODE_DB_PATH == "/tmp/test.db"  # type: ignore[attr-defined]


def test_missing_token_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing DISCORD_BOT_TOKEN raises RuntimeError."""
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="DISCORD_BOT_TOKEN is required"):
        _reload_config()


def test_empty_token_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty DISCORD_BOT_TOKEN raises RuntimeError."""
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "")

    with pytest.raises(RuntimeError, match="DISCORD_BOT_TOKEN is required"):
        _reload_config()


def test_dev_guild_id_default_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """TEAMODE_DEV_GUILD_ID is None when the env var is unset."""
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token-abcd")
    monkeypatch.delenv("TEAMODE_DEV_GUILD_ID", raising=False)

    cfg = _reload_config()

    assert cfg.TEAMODE_DEV_GUILD_ID is None  # type: ignore[attr-defined]


def test_dev_guild_id_populated_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """TEAMODE_DEV_GUILD_ID picks up the env var value when set."""
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token-abcd")
    monkeypatch.setenv("TEAMODE_DEV_GUILD_ID", "123456789012345678")

    cfg = _reload_config()

    assert cfg.TEAMODE_DEV_GUILD_ID == "123456789012345678"  # type: ignore[attr-defined]
