"""Voice connection helpers for TeaMode.

This module is a thin shim over discord.py voice primitives so the rest of
the codebase never imports ``discord.FFmpegPCMAudio`` directly.  All three
public helpers propagate exceptions to the caller; the Discord-facing layer
in ``app.bot`` is responsible for turning failures into user-visible
responses.
"""

import asyncio
import logging
from pathlib import Path

import discord

logger = logging.getLogger(__name__)

# Resolved once at import so the same Path object is reused per playback call.
REVERIE_PATH: Path = (Path(__file__).parent / ".." / "assets" / "reverie.wav").resolve()


async def connect(voice_channel: discord.VoiceChannel) -> discord.VoiceClient:
    """Connect to *voice_channel* and return the resulting VoiceClient.

    Propagates any exception raised by discord.py — the caller decides how to
    surface a connect failure to the user.
    """
    return await voice_channel.connect()  # type: ignore[return-value]


def play_reverie(voice_client: discord.VoiceClient) -> None:
    """Start playback of the reverie chime on *voice_client*.

    The call returns immediately; it does **not** wait for playback to finish.
    Waiting and subsequent disconnection are composed by the session layer
    (Stage 4).  Propagates any exception raised by discord.py.
    """
    voice_client.play(discord.FFmpegPCMAudio(str(REVERIE_PATH)))


async def disconnect(voice_client: discord.VoiceClient) -> None:
    """Disconnect *voice_client* from its voice channel.

    Propagates any exception raised by discord.py.
    """
    await voice_client.disconnect()


async def play_reverie_then_disconnect(voice_client: discord.VoiceClient) -> bool:
    """Play the reverie chime, wait for it to finish, then disconnect.

    Returns ``True`` if playback completed without error, ``False`` if playback
    failed (either a synchronous error from ``play()`` or an error reported via
    the ``after`` callback).  Disconnect is always attempted regardless of
    playback outcome; a disconnect error is logged at WARNING level and does
    not affect the returned boolean.
    """
    done: asyncio.Event = asyncio.Event()
    # Use a single-element list so the after callback (running in a separate
    # thread) can mutate the flag without a nonlocal closure — lists are safe
    # for cross-thread reads once the event fires.
    success: list[bool] = [True]
    loop = voice_client.loop

    def after(error: BaseException | None) -> None:
        if error is not None:
            success[0] = False
        loop.call_soon_threadsafe(done.set)

    play_ok = True
    try:
        voice_client.play(discord.FFmpegPCMAudio(str(REVERIE_PATH)), after=after)
    except Exception:
        # Synchronous failure (e.g. ffmpeg not on PATH). Skip waiting on the
        # event — the after callback will never fire.
        play_ok = False
        success[0] = False

    if play_ok:
        await done.wait()

    try:
        await voice_client.disconnect()
    except Exception as exc:
        logger.warning("voice disconnect error after reverie playback: %s", exc)

    return success[0]
