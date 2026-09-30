"""Tests for app.config environment-variable loader."""

import importlib
import logging
import sys
from datetime import timezone
from zoneinfo import ZoneInfo

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


def test_dev_guild_ids_default_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """TEAMODE_DEV_GUILD_IDS is empty when the env var is unset."""
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token-abcd")
    monkeypatch.delenv("TEAMODE_DEV_GUILD_ID", raising=False)

    cfg = _reload_config()

    assert cfg.TEAMODE_DEV_GUILD_IDS == []  # type: ignore[attr-defined]


def test_dev_guild_ids_single(monkeypatch: pytest.MonkeyPatch) -> None:
    """TEAMODE_DEV_GUILD_IDS parses a single guild ID as a one-element list."""
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token-abcd")
    monkeypatch.setenv("TEAMODE_DEV_GUILD_ID", "123456789012345678")

    cfg = _reload_config()

    assert cfg.TEAMODE_DEV_GUILD_IDS == [123456789012345678]  # type: ignore[attr-defined]


def test_dev_guild_ids_comma_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    """TEAMODE_DEV_GUILD_IDS parses comma-separated values into a list of ints."""
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token-abcd")
    monkeypatch.setenv("TEAMODE_DEV_GUILD_ID", "111111111111111111,222222222222222222")

    cfg = _reload_config()

    assert cfg.TEAMODE_DEV_GUILD_IDS == [111111111111111111, 222222222222222222]  # type: ignore[attr-defined]


def test_timezone_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    """A valid IANA timezone name is parsed and exposed as configured."""
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token-abcd")
    monkeypatch.setenv("TEAMODE_TIMEZONE", "Europe/Berlin")

    cfg = _reload_config()

    assert cfg.TEAMODE_TIMEZONE == ZoneInfo("Europe/Berlin")  # type: ignore[attr-defined]


def test_timezone_unset_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset TEAMODE_TIMEZONE falls back to DEFAULT_TIMEZONE."""
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token-abcd")
    monkeypatch.delenv("TEAMODE_TIMEZONE", raising=False)

    cfg = _reload_config()

    assert cfg.TEAMODE_TIMEZONE == ZoneInfo("America/Los_Angeles")  # type: ignore[attr-defined]


def test_timezone_invalid_logs_warning_and_falls_back(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """An invalid IANA name logs a WARNING and falls back to the default."""
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token-abcd")
    monkeypatch.setenv("TEAMODE_TIMEZONE", "Not/A_Real_Zone")

    with caplog.at_level(logging.WARNING):
        cfg = _reload_config()

    assert cfg.TEAMODE_TIMEZONE == ZoneInfo("America/Los_Angeles")  # type: ignore[attr-defined]
    assert "Not/A_Real_Zone" in caplog.text


def test_timezone_default_unavailable_falls_back_to_utc(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """If even the default zone is unavailable, fall back to UTC with a WARNING."""
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token-abcd")
    monkeypatch.setenv("TEAMODE_TIMEZONE", "Not/A_Real_Zone")
    monkeypatch.setattr("app.constants.DEFAULT_TIMEZONE", "Also/Not_Real")

    with caplog.at_level(logging.WARNING):
        cfg = _reload_config()

    assert cfg.TEAMODE_TIMEZONE == timezone.utc  # type: ignore[attr-defined]
    assert "UTC" in caplog.text
