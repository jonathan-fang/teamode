"""Single-instance PID lock.

Two live bot instances sharing one Discord token both receive every
interaction, and the loser crashes with ``40060 Interaction already
acknowledged`` / ``404 Unknown interaction``. This module checks for a
live prior instance before startup continues, and cleans up its own
PID file on exit.
"""

from __future__ import annotations

import atexit
import logging
import os

logger = logging.getLogger(__name__)


def is_pid_alive(pid: int) -> bool:
    """Return True if ``pid`` refers to a live process we can see.

    ``ProcessLookupError`` means the process is gone (stale). A
    ``PermissionError`` means the process exists but is owned by
    another user — still alive from our perspective.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_pid(pid_file_path: str) -> int | None:
    """Read and parse the PID file. Returns None if absent or unparseable."""
    try:
        with open(pid_file_path, encoding="utf-8") as f:
            content = f.read().strip()
    except FileNotFoundError:
        return None

    try:
        return int(content)
    except ValueError:
        return None


def write_pid(pid_file_path: str, pid: int) -> None:
    """Overwrite the PID file with ``pid``."""
    with open(pid_file_path, "w", encoding="utf-8") as f:
        f.write(str(pid))


def remove_pid_file(pid_file_path: str, expected_pid: int) -> None:
    """Remove the PID file, but only if it still holds our own PID.

    Registered as an ``atexit`` handler; a safety check so we never
    delete a PID file a newer instance has since claimed.
    """
    current = read_pid(pid_file_path)
    if current != expected_pid:
        return
    try:
        os.remove(pid_file_path)
    except FileNotFoundError:
        pass


def acquire_pid_lock(pid_file_path: str) -> None:
    """Acquire the single-instance PID lock or exit the process.

    If a live instance already holds the lock, logs an ERROR and exits
    with a non-zero status without touching anything else. Otherwise
    (stale or absent PID file) writes our own PID and registers an
    ``atexit`` cleanup handler.
    """
    existing_pid = read_pid(pid_file_path)
    if existing_pid is not None and is_pid_alive(existing_pid):
        logger.error(
            "Another TeaMode instance is already running (pid %d) — exiting.",
            existing_pid,
        )
        raise SystemExit(1)

    our_pid = os.getpid()
    write_pid(pid_file_path, our_pid)
    atexit.register(remove_pid_file, pid_file_path, our_pid)
