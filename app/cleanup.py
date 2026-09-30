"""Pure message classification for ``/teamode-clear``.

No ``discord`` import — operates on plain values (``content: str``, a
list of embed titles) so it is unit-testable in isolation and reusable by
the Discord-facing command handler in
``app.discord_bot.commands``/``app.discord_bot.clear``.

Every matcher below is derived from the copy templates in
``app.constants`` — never a duplicated literal — so a User edit to one of
those constants (e.g. a smoke-test value) keeps classification in sync
automatically. Templates with ``{placeholders}`` are turned into a regex
that matches the literal parts verbatim and each field with a
non-greedy wildcard (see :func:`_template_pattern`).
"""

from __future__ import annotations

import re
import string
from collections.abc import Sequence

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
    MSG_WRAP_UP_NUDGE,
    MSG_WRAP_UP_NUDGE_ONE,
    TIMER_EMBED_TITLE,
    WELCOME_EMBED_TITLE,
)

_FORMATTER = string.Formatter()


def _template_pattern(template: str) -> re.Pattern[str]:
    """Compile *template* (a ``str.format`` template) into a full-match regex.

    Each literal chunk is escaped verbatim; each ``{field}`` placeholder
    becomes a non-greedy ``.*?`` wildcard (``re.DOTALL`` so a placeholder
    can also swallow embedded newlines, e.g. a multi-line durations list).
    """
    pieces: list[str] = []
    for literal_text, field_name, _format_spec, _conversion in _FORMATTER.parse(
        template
    ):
        pieces.append(re.escape(literal_text))
        if field_name is not None:
            pieces.append(r".*?")
    return re.compile("^" + "".join(pieces) + "$", re.DOTALL)


# ---------------------------------------------------------------------------
# Never delete-eligible — checked first
# ---------------------------------------------------------------------------

_TIMER_EMBED_TITLE_RE = _template_pattern(TIMER_EMBED_TITLE)
_HANDOFF_ANNOUNCE_RE = _template_pattern(HANDOFF_ANNOUNCE)
_AUTO_HANDOFF_ANNOUNCE_RE = _template_pattern(AUTO_HANDOFF_ANNOUNCE)

# ---------------------------------------------------------------------------
# Delete-eligible matchers
# ---------------------------------------------------------------------------

_PARTICIPANT_PROMPT_RE = _template_pattern(MSG_PARTICIPANT_PROMPT)
_END_OF_SESSION_MENTION_RE = _template_pattern(END_OF_SESSION_MENTION)
_FOLLOWUP_WHY_PROMPT_RE = _template_pattern(FOLLOWUP_WHY_PROMPT)
_WRAP_UP_NUDGE_RE = _template_pattern(MSG_WRAP_UP_NUDGE)
_CHAIN_PROMPT_STREAK_RE = _template_pattern(CHAIN_PROMPT_STREAK)
_BREAK_STARTED_RE = _template_pattern(BREAK_STARTED)


def is_delete_eligible(*, content: str, embed_titles: Sequence[str]) -> bool:
    """Return whether a bot-authored message is past TeaMode clutter.

    *content* is the message's text content (``""`` if none). *embed_titles*
    is the list of that message's embed titles (empty if none — Discord
    allows multiple embeds per message, though TeaMode only ever sends one).

    Authorship (bot vs. human) is the caller's responsibility — this
    function assumes it is already looking at a bot-authored message.
    """
    # Timer messages can never match another rule — checked first. The
    # solo-grace final content (SOLO_GRACE_ENDED) lives on the timer
    # message, so it is protected by the same embed-title check.
    if any(_TIMER_EMBED_TITLE_RE.fullmatch(title) for title in embed_titles):
        return False

    # Handoff notices are never delete-eligible.
    if _HANDOFF_ANNOUNCE_RE.fullmatch(content) or _AUTO_HANDOFF_ANNOUNCE_RE.fullmatch(
        content
    ):
        return False

    # Welcome — embed title match; content may also carry MSG_PENDING_EXPIRED
    # after pending expiry, but the embed title alone is sufficient.
    if any(title == WELCOME_EMBED_TITLE for title in embed_titles):
        return True

    # Set Intention participant prompt.
    if _PARTICIPANT_PROMPT_RE.fullmatch(content):
        return True

    # Time's up — content and/or embed title.
    if (
        content == END_OF_SESSION_NO_MENTION
        or _END_OF_SESSION_MENTION_RE.fullmatch(content)
        or any(title == END_EMBED_TITLE for title in embed_titles)
    ):
        return True

    # Reflect — content alone identifies it; the embed (present or already
    # stripped at the next session start) doesn't change the verdict.
    if content == FOLLOWUP_PROMPT:
        return True

    # The "⛔ why" follow-up line.
    if _FOLLOWUP_WHY_PROMPT_RE.fullmatch(content):
        return True

    # Wrap-up nudge — either minute-count form.
    if content == MSG_WRAP_UP_NUDGE_ONE or _WRAP_UP_NUDGE_RE.fullmatch(content):
        return True

    # Chaining prompts.
    if content == CHAIN_PROMPT or _CHAIN_PROMPT_STREAK_RE.fullmatch(content):
        return True

    # Break messages.
    if content in (BREAK_OVER, BREAK_CANCELLED) or _BREAK_STARTED_RE.fullmatch(content):
        return True

    return False
