"""Tests for app.pidlock — single-instance PID lock."""

import atexit
import os
from pathlib import Path

import pytest

from app.pidlock import (
    acquire_pid_lock,
    is_pid_alive,
    read_pid,
    remove_pid_file,
    write_pid,
)


def test_is_pid_alive_true_for_current_process() -> None:
    assert is_pid_alive(os.getpid()) is True


def test_is_pid_alive_false_for_dead_process(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_kill(pid: int, sig: int) -> None:
        raise ProcessLookupError

    monkeypatch.setattr(os, "kill", fake_kill)
    assert is_pid_alive(12345) is False


def test_is_pid_alive_true_for_permission_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_kill(pid: int, sig: int) -> None:
        raise PermissionError

    monkeypatch.setattr(os, "kill", fake_kill)
    assert is_pid_alive(12345) is True


def test_read_pid_absent_file_returns_none(tmp_path: Path) -> None:
    pid_file = tmp_path / "teamode.pid"
    assert read_pid(str(pid_file)) is None


def test_read_pid_unparseable_content_returns_none(tmp_path: Path) -> None:
    pid_file = tmp_path / "teamode.pid"
    pid_file.write_text("not-a-pid")
    assert read_pid(str(pid_file)) is None


def test_write_and_read_pid_round_trip(tmp_path: Path) -> None:
    pid_file = tmp_path / "teamode.pid"
    write_pid(str(pid_file), 4242)
    assert read_pid(str(pid_file)) == 4242


def test_acquire_pid_lock_live_pid_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid_file = tmp_path / "teamode.pid"
    write_pid(str(pid_file), 99999)
    monkeypatch.setattr("app.pidlock.is_pid_alive", lambda pid: True)

    with pytest.raises(SystemExit) as exc_info:
        acquire_pid_lock(str(pid_file))

    assert exc_info.value.code != 0
    # Existing PID file must be left untouched — no overwrite for a live lock.
    assert read_pid(str(pid_file)) == 99999


def test_acquire_pid_lock_stale_pid_overwrites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid_file = tmp_path / "teamode.pid"
    write_pid(str(pid_file), 99999)
    monkeypatch.setattr("app.pidlock.is_pid_alive", lambda pid: False)
    monkeypatch.setattr(atexit, "register", lambda *a, **k: None)

    acquire_pid_lock(str(pid_file))

    assert read_pid(str(pid_file)) == os.getpid()


def test_acquire_pid_lock_absent_file_creates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid_file = tmp_path / "teamode.pid"
    monkeypatch.setattr(atexit, "register", lambda *a, **k: None)

    acquire_pid_lock(str(pid_file))

    assert read_pid(str(pid_file)) == os.getpid()


def test_acquire_pid_lock_registers_atexit_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid_file = tmp_path / "teamode.pid"
    captured_args: list[str] = []

    def fake_register(func: object, path: str, pid: int) -> None:
        assert func is remove_pid_file
        captured_args.append(path)
        captured_args.append(str(pid))

    monkeypatch.setattr(atexit, "register", fake_register)

    acquire_pid_lock(str(pid_file))

    assert captured_args == [str(pid_file), str(os.getpid())]

    # Invoke the handler directly (same call the registration would make)
    # and confirm cleanup happens.
    remove_pid_file(str(pid_file), os.getpid())
    assert not pid_file.exists()


def test_remove_pid_file_skips_when_pid_mismatched(tmp_path: Path) -> None:
    pid_file = tmp_path / "teamode.pid"
    write_pid(str(pid_file), 55555)

    remove_pid_file(str(pid_file), os.getpid())

    # A newer instance's PID must survive — we didn't write it.
    assert read_pid(str(pid_file)) == 55555


def test_remove_pid_file_missing_file_is_noop(tmp_path: Path) -> None:
    pid_file = tmp_path / "teamode.pid"
    # Should not raise even though the file was never created.
    remove_pid_file(str(pid_file), os.getpid())
