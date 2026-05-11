"""Tests for app.voice — connect, play_reverie, disconnect, play_reverie_then_disconnect."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.voice import (
    REVERIE_PATH,
    connect,
    disconnect,
    play_reverie,
    play_reverie_then_disconnect,
)


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


# ---------------------------------------------------------------------------
# play_reverie_then_disconnect
# ---------------------------------------------------------------------------


def _make_fake_voice_client() -> MagicMock:
    """Return a MagicMock voice client wired with an asyncio event loop."""
    fake_client = MagicMock()
    fake_client.loop = asyncio.get_event_loop()
    fake_client.disconnect = AsyncMock()
    return fake_client


@pytest.mark.asyncio
async def test_play_reverie_then_disconnect_success_path() -> None:
    """Success path: after callback fires with None → returns True, disconnect called once."""
    fake_client = _make_fake_voice_client()
    captured_after: list = []

    def fake_play(audio_source, *, after=None, **kwargs):  # type: ignore[no-untyped-def]
        captured_after.append(after)

    fake_client.play.side_effect = fake_play

    with patch("app.voice.discord.FFmpegPCMAudio") as mock_ffmpeg:
        mock_audio = MagicMock()
        mock_ffmpeg.return_value = mock_audio

        async def drive() -> bool:
            result_future = asyncio.ensure_future(
                play_reverie_then_disconnect(fake_client)
            )
            # Yield so the coroutine reaches await done.wait()
            await asyncio.sleep(0)
            # Fire the after callback with no error (simulating normal playback end)
            assert captured_after, (
                "play() was not called before we tried to invoke after"
            )
            captured_after[0](None)
            # Yield so call_soon_threadsafe callback (done.set) is processed
            await asyncio.sleep(0)
            return await result_future

        result = await drive()

    mock_ffmpeg.assert_called_once_with(str(REVERIE_PATH))
    fake_client.play.assert_called_once()
    _, kwargs = fake_client.play.call_args
    assert kwargs.get("after") is not None
    fake_client.disconnect.assert_called_once()
    assert result is True


@pytest.mark.asyncio
async def test_play_reverie_then_disconnect_after_callback_error() -> None:
    """After callback fires with exception → returns False, disconnect still called."""
    fake_client = _make_fake_voice_client()
    captured_after: list = []

    def fake_play(audio_source, *, after=None, **kwargs):  # type: ignore[no-untyped-def]
        captured_after.append(after)

    fake_client.play.side_effect = fake_play

    with patch("app.voice.discord.FFmpegPCMAudio"):

        async def drive() -> bool:
            result_future = asyncio.ensure_future(
                play_reverie_then_disconnect(fake_client)
            )
            await asyncio.sleep(0)
            captured_after[0](RuntimeError("encoder error"))
            await asyncio.sleep(0)
            return await result_future

        result = await drive()

    fake_client.disconnect.assert_called_once()
    assert result is False


@pytest.mark.asyncio
async def test_play_reverie_then_disconnect_synchronous_play_error() -> None:
    """Synchronous play() raises → returns False immediately, disconnect still called."""
    fake_client = _make_fake_voice_client()
    fake_client.play.side_effect = RuntimeError("ffmpeg not found")

    with patch("app.voice.discord.FFmpegPCMAudio"):
        result = await play_reverie_then_disconnect(fake_client)

    fake_client.disconnect.assert_called_once()
    assert result is False


@pytest.mark.asyncio
async def test_play_reverie_then_disconnect_disconnect_error_does_not_mask_success() -> (
    None
):
    """Disconnect raising must not change the playback-success return value."""
    fake_client = _make_fake_voice_client()
    fake_client.disconnect = AsyncMock(side_effect=RuntimeError("disconnect error"))
    captured_after: list = []

    def fake_play(audio_source, *, after=None, **kwargs):  # type: ignore[no-untyped-def]
        captured_after.append(after)

    fake_client.play.side_effect = fake_play

    with patch("app.voice.discord.FFmpegPCMAudio"):

        async def drive() -> bool:
            result_future = asyncio.ensure_future(
                play_reverie_then_disconnect(fake_client)
            )
            await asyncio.sleep(0)
            captured_after[0](None)  # playback succeeded
            await asyncio.sleep(0)
            return await result_future

        result = await drive()

    # Disconnect was attempted (and raised), but return value still reflects playback success
    fake_client.disconnect.assert_called_once()
    assert result is True
