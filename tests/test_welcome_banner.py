"""Tests for the ASCII teacup banner at the top of the welcome embed."""

from __future__ import annotations

from app.constants import (
    TEACUP_BANNER,
    WELCOME_BANNER_BLOCK,
    WELCOME_EMBED_DESCRIPTION,
    WELCOME_EMBED_TITLE,
)
from app.discord_bot.views import COLORS, _build_welcome_embed


def test_welcome_embed_starts_with_banner_block() -> None:
    embed = _build_welcome_embed()
    expected_banner_block = WELCOME_BANNER_BLOCK.format(banner=TEACUP_BANNER)

    assert embed.description is not None
    assert embed.description.startswith(expected_banner_block)


def test_welcome_embed_description_followed_by_unchanged_body() -> None:
    embed = _build_welcome_embed()
    expected_banner_block = WELCOME_BANNER_BLOCK.format(banner=TEACUP_BANNER)

    assert embed.description == expected_banner_block + WELCOME_EMBED_DESCRIPTION


def test_welcome_embed_description_within_discord_limit() -> None:
    embed = _build_welcome_embed()

    assert embed.description is not None
    assert len(embed.description) <= 4096


def test_welcome_embed_title_and_color_unchanged() -> None:
    embed = _build_welcome_embed()

    assert embed.title == WELCOME_EMBED_TITLE
    assert embed.color == COLORS["active"]
