"""Tests for teamode.py startup helpers (ffmpeg probe)."""

import logging

import pytest

import teamode


def test_check_ffmpeg_missing_logs_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(teamode.shutil, "which", lambda name: None)

    with caplog.at_level(logging.WARNING):
        teamode.check_ffmpeg()

    assert teamode.FFMPEG_MISSING_WARNING in caplog.text


def test_check_ffmpeg_present_logs_nothing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(teamode.shutil, "which", lambda name: "/usr/bin/ffmpeg")

    with caplog.at_level(logging.WARNING):
        teamode.check_ffmpeg()

    assert caplog.text == ""
