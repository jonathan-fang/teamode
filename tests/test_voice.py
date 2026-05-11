"""Tests for app.voice — connect, play_reverie, disconnect."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.voice import REVERIE_PATH, connect, disconnect, play_reverie


# ---------------------------------------------------------------------------
# connect
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_calls_channel_connect_once() -> None:
    """connect() should call voice_channel.connect() exactly once and return
    its result."""
    fake_client = MagicMock()
    fake_channel = MagicMock()
    fake_channel.connect = AsyncMock(return_value=fake_client)

    result = await connect(fake_channel)

    fake_channel.connect.assert_called_once()
    assert result is fake_client


@pytest.mark.asyncio
async def test_connect_propagates_exception() -> None:
    """connect() must not swallow exceptions from voice_channel.connect()."""
    fake_channel = MagicMock()
    fake_channel.connect = AsyncMock(side_effect=RuntimeError("connect failed"))

    with pytest.raises(RuntimeError, match="connect failed"):
        await connect(fake_channel)


# ---------------------------------------------------------------------------
# play_reverie
# ---------------------------------------------------------------------------


def test_play_reverie_calls_play_once() -> None:
    """play_reverie() should call voice_client.play() exactly once."""
    fake_client = MagicMock()

    with patch("app.voice.discord.FFmpegPCMAudio"):
        play_reverie(fake_client)

    fake_client.play.assert_called_once()


def test_play_reverie_uses_resolved_reverie_path() -> None:
    """play_reverie() must construct FFmpegPCMAudio with the absolute path of
    assets/reverie.wav."""
    fake_client = MagicMock()

    with patch("app.voice.discord.FFmpegPCMAudio") as mock_ffmpeg:
        mock_audio = MagicMock()
        mock_ffmpeg.return_value = mock_audio

        play_reverie(fake_client)

        mock_ffmpeg.assert_called_once_with(str(REVERIE_PATH))
        assert REVERIE_PATH.is_absolute()
        assert REVERIE_PATH.name == "reverie.wav"
        fake_client.play.assert_called_once_with(mock_audio)


def test_play_reverie_propagates_exception() -> None:
    """play_reverie() must not swallow exceptions raised during playback."""
    fake_client = MagicMock()
    fake_client.play.side_effect = RuntimeError("play failed")

    with patch("app.voice.discord.FFmpegPCMAudio"):
        with pytest.raises(RuntimeError, match="play failed"):
            play_reverie(fake_client)


# ---------------------------------------------------------------------------
# disconnect
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disconnect_calls_disconnect_once() -> None:
    """disconnect() should call voice_client.disconnect() exactly once."""
    fake_client = MagicMock()
    fake_client.disconnect = AsyncMock()

    await disconnect(fake_client)

    fake_client.disconnect.assert_called_once()


@pytest.mark.asyncio
async def test_disconnect_propagates_exception() -> None:
    """disconnect() must not swallow exceptions from voice_client.disconnect()."""
    fake_client = MagicMock()
    fake_client.disconnect = AsyncMock(side_effect=RuntimeError("disconnect failed"))

    with pytest.raises(RuntimeError, match="disconnect failed"):
        await disconnect(fake_client)
