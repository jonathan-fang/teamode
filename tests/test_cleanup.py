"""Tests for the pure /clear message classifier (app/cleanup.py).

Fixture strings are built by formatting the constants themselves, never
hand-written literals, so classification stays derived from
``app/constants.py`` — the same contract ``app/cleanup.py`` relies on.
"""

from __future__ import annotations

from app.cleanup import is_delete_eligible
from app.constants import (
    AUTO_HANDOFF_ANNOUNCE,
    BREAK_CANCELLED,
    BREAK_OVER,
    BREAK_STARTED,
    CHAIN_PROMPT,
    CHAIN_PROMPT_STREAK,
    END_EMBED_TITLE,
    END_OF_SESSION_MENTION,
    END_OF_SESSION_NO_MENTION,
    FOLLOWUP_PROMPT,
    FOLLOWUP_WHY_PROMPT,
    HANDOFF_ANNOUNCE,
    MSG_PARTICIPANT_PROMPT,
    MSG_PENDING_EXPIRED,
    MSG_WRAP_UP_NUDGE,
    MSG_WRAP_UP_NUDGE_ONE,
    REFLECT_EMBED_TITLE,
    SESSION_RECORD_INTENTION_SET,
    SESSION_RECORD_META,
    SOLO_GRACE_ENDED,
    STREAK_DURATION_ITEM,
    STREAK_DURATION_SEPARATOR,
    TIMER_EMBED_TITLE,
    TIMER_TIME_RANGE,
    WELCOME_EMBED_TITLE,
)

# ---------------------------------------------------------------------------
# Delete-eligible fixtures
# ---------------------------------------------------------------------------


def test_welcome_is_delete_eligible() -> None:
    assert is_delete_eligible(content="", embed_titles=[WELCOME_EMBED_TITLE])


def test_expired_welcome_is_delete_eligible() -> None:
    # Content carries MSG_PENDING_EXPIRED after pending expiry; the embed
    # title alone is enough to classify it.
    assert is_delete_eligible(
        content=MSG_PENDING_EXPIRED, embed_titles=[WELCOME_EMBED_TITLE]
    )


def test_set_intention_prompt_no_mentions_is_delete_eligible() -> None:
    content = MSG_PARTICIPANT_PROMPT.format(mentions="")
    assert is_delete_eligible(content=content, embed_titles=[])


def test_set_intention_prompt_with_mentions_is_delete_eligible() -> None:
    content = MSG_PARTICIPANT_PROMPT.format(mentions="<@111> <@222> ")
    assert is_delete_eligible(content=content, embed_titles=[])


def test_times_up_with_mention_is_delete_eligible() -> None:
    content = END_OF_SESSION_MENTION.format(mentions="<@111> <@222>")
    assert is_delete_eligible(content=content, embed_titles=[END_EMBED_TITLE])


def test_times_up_no_mention_is_delete_eligible() -> None:
    assert is_delete_eligible(
        content=END_OF_SESSION_NO_MENTION, embed_titles=[END_EMBED_TITLE]
    )


def test_times_up_content_only_is_delete_eligible() -> None:
    # Content alone (no embed title passed) still classifies as Time's up.
    assert is_delete_eligible(content=END_OF_SESSION_NO_MENTION, embed_titles=[])


def test_times_up_embed_title_only_is_delete_eligible() -> None:
    # Embed title alone (content empty) still classifies as Time's up.
    assert is_delete_eligible(content="", embed_titles=[END_EMBED_TITLE])


def test_reflect_with_embed_is_delete_eligible() -> None:
    assert is_delete_eligible(
        content=FOLLOWUP_PROMPT, embed_titles=[REFLECT_EMBED_TITLE]
    )


def test_reflect_without_embed_is_delete_eligible() -> None:
    # The embed is stripped at the next session start — content alone
    # still identifies Reflect.
    assert is_delete_eligible(content=FOLLOWUP_PROMPT, embed_titles=[])


def test_followup_why_line_is_delete_eligible() -> None:
    content = FOLLOWUP_WHY_PROMPT.format(facilitator_id="111")
    assert is_delete_eligible(content=content, embed_titles=[])


def test_wrap_up_nudge_is_delete_eligible() -> None:
    content = MSG_WRAP_UP_NUDGE.format(minutes=3)
    assert is_delete_eligible(content=content, embed_titles=[])


def test_wrap_up_nudge_different_minute_count_is_delete_eligible() -> None:
    content = MSG_WRAP_UP_NUDGE.format(minutes=7)
    assert is_delete_eligible(content=content, embed_titles=[])


def test_wrap_up_nudge_one_minute_is_delete_eligible() -> None:
    assert is_delete_eligible(content=MSG_WRAP_UP_NUDGE_ONE, embed_titles=[])


def test_chain_prompt_is_delete_eligible() -> None:
    assert is_delete_eligible(content=CHAIN_PROMPT, embed_titles=[])


def test_chain_prompt_streak_is_delete_eligible() -> None:
    durations = STREAK_DURATION_SEPARATOR.join(
        STREAK_DURATION_ITEM.format(minutes=m) for m in (25, 30)
    )
    content = CHAIN_PROMPT_STREAK.format(count=2, durations=durations)
    assert is_delete_eligible(content=content, embed_titles=[])


def test_chain_prompt_streak_different_counts_is_delete_eligible() -> None:
    durations = STREAK_DURATION_SEPARATOR.join(
        STREAK_DURATION_ITEM.format(minutes=m) for m in (50, 50, 25)
    )
    content = CHAIN_PROMPT_STREAK.format(count=3, durations=durations)
    assert is_delete_eligible(content=content, embed_titles=[])


def test_break_started_is_delete_eligible() -> None:
    content = BREAK_STARTED.format(hhmm="3:45 PM")
    assert is_delete_eligible(content=content, embed_titles=[])


def test_break_over_is_delete_eligible() -> None:
    assert is_delete_eligible(content=BREAK_OVER, embed_titles=[])


def test_break_cancelled_is_delete_eligible() -> None:
    assert is_delete_eligible(content=BREAK_CANCELLED, embed_titles=[])


# ---------------------------------------------------------------------------
# Never delete-eligible fixtures
# ---------------------------------------------------------------------------


def test_timer_message_is_never_delete_eligible() -> None:
    for minutes in (5, 10, 25, 50):
        title = TIMER_EMBED_TITLE.format(duration=minutes)
        assert not is_delete_eligible(
            content="⏳ 04:30 remaining", embed_titles=[title]
        )


def test_timer_message_solo_grace_ended_is_never_delete_eligible() -> None:
    # The solo-grace final content lives on the timer message — the embed
    # title check protects it regardless of content.
    title = TIMER_EMBED_TITLE.format(duration=25)
    assert not is_delete_eligible(content=SOLO_GRACE_ENDED, embed_titles=[title])


def test_handoff_announce_is_never_delete_eligible() -> None:
    content = HANDOFF_ANNOUNCE.format(
        old_facilitator_id="111", new_facilitator_id="222"
    )
    assert not is_delete_eligible(content=content, embed_titles=[])


def test_auto_handoff_announce_is_never_delete_eligible() -> None:
    content = AUTO_HANDOFF_ANNOUNCE.format(
        old_facilitator_id="111", new_facilitator_id="222"
    )
    assert not is_delete_eligible(content=content, embed_titles=[])


def test_unrelated_bot_message_is_never_delete_eligible() -> None:
    assert not is_delete_eligible(content="hello world", embed_titles=[])


def test_arbitrary_text_is_never_delete_eligible() -> None:
    assert not is_delete_eligible(content="", embed_titles=["Some other embed"])


def test_finalized_session_record_is_never_delete_eligible() -> None:
    # The plain-text record a timer message is rewritten to at session end
    # (embed stripped) matches no delete-eligible rule, so it falls through
    # to the default False — protected without any dedicated classifier
    # rule needed.
    intention_line = SESSION_RECORD_INTENTION_SET.format(intention="ship it")
    meta_line = SESSION_RECORD_META.format(duration=25, facilitator_id="111")
    range_line = TIMER_TIME_RANGE.format(start="14:00", end="14:25")
    content = f"{intention_line}\n{meta_line}\n{range_line}"
    assert not is_delete_eligible(content=content, embed_titles=[])
