"""Voice connection helpers for TeaMode.

This module is a thin shim over discord.py voice primitives so the rest of
the codebase never imports ``discord.FFmpegPCMAudio`` directly.  All three
public helpers propagate exceptions to the caller; the Discord-facing layer
in ``app.bot`` is responsible for turning failures into user-visible
responses.
"""

from pathlib import Path

import discord

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
