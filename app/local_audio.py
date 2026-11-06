"""Host-machine chime playback for Groove sessions.

A Groove session (``/groove``) has no voice connection, so its chimes play
on the machine running Ocha instead, via ``ffplay`` (shipped with ffmpeg,
which is already required for voice playback). Under WSL, ffplay reaches
the Windows speakers through WSLg's PulseAudio server.

No ``discord`` import. Never raises: a disabled toggle, a missing
``ffplay``, or a non-zero exit is logged and reported as ``False`` so a
failed chime never breaks the session flow.
"""

import asyncio
import logging
import subprocess
from collections.abc import Awaitable, Callable
from pathlib import Path

from app import config

logger = logging.getLogger(__name__)

# argv for one quiet, windowless, play-once ffplay run; the path is appended.
FFPLAY_ARGS: tuple[str, ...] = (
    "ffplay",
    "-nodisp",
    "-autoexit",
    "-loglevel",
    "quiet",
)

Spawn = Callable[..., Awaitable[asyncio.subprocess.Process]]


async def play(
    path: Path,
    *,
    spawn: Spawn = asyncio.create_subprocess_exec,
) -> bool:
    """Play *path* once on the host and wait for it to finish.

    Returns ``True`` if ffplay exited cleanly, ``False`` if playback was
    skipped (``TEAMODE_GROOVE_LOCAL_AUDIO`` off) or failed. *spawn* is the
    subprocess seam replaced in tests.
    """
    if not config.TEAMODE_GROOVE_LOCAL_AUDIO:
        logger.warning("Skipping local chime %s — local audio is disabled", path.name)
        return False
    try:
        proc = await spawn(
            *FFPLAY_ARGS,
            str(path),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        logger.warning("Failed to start ffplay for %s: %s", path.name, exc)
        return False
    returncode = await proc.wait()
    if returncode != 0:
        logger.warning("ffplay exited %s playing %s", returncode, path.name)
        return False
    return True
