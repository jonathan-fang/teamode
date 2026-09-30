"""Central home for every tunable number, palette value, and Discord-facing
string in TeaMode.

Anything Ocha sends to Discord (message content, embed titles/descriptions,
button labels, modal titles/labels, slash-command descriptions, voice
channel statuses) and every tunable number (durations, timeouts, limits,
intervals, widths) lives here as a named constant. Variable parts use
``str.format`` placeholders (e.g. ``{seconds}``) — callers do
``CONSTANT.format(seconds=...)``.

This module must not import ``discord`` or ``app.config`` (or anything from
``app.discord_bot``) — it is pure data so it can be read and tested in
isolation.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

DURATIONS_MINUTES: tuple[int, ...] = (5, 10, 25, 50)  # only allows int

RATE_LIMIT_WINDOW_SECONDS = 300
RATE_LIMIT_ALLOWANCE = 3
GUILD_DAILY_CAP = 50
WRAP_UP_MINUTES = 3  # 3
NUDGE_MIN_DURATION_MINUTES = 10  # 10
PENDING_TIMEOUT_SECONDS = 600  # 600
BREAK_MINUTES = 5
GO_AGAIN_TIMEOUT_SECONDS = 180
CLEAR_SCAN_LIMIT = 200

FOLLOWUP_TIMEOUT_SECONDS = 180  # moved from app/discord_bot/lifecycle.py
SOLO_GRACE_SECONDS = 300  # 300 moved from app/discord_bot/lifecycle.py
EDIT_INTERVAL_SECONDS = 10  # moved from app/discord_bot/timer.py
BACKOFF_FLOOR_DEFAULT = 10.0  # moved from app/discord_bot/views.py
BACKOFF_FLOOR_CAP = 60.0  # moved from app/discord_bot/timer.py

WELCOME_PROMPT_DELAY_SECONDS = 1.0  # moved from app/discord_bot/commands.py
INTENTION_MAX_LENGTH = 4000  # moved from app/discord_bot/views.py

PROGRESS_BAR_WIDTH = 10
TIMER_FIELD_VALUE_MAX_LENGTH = 1024  # Discord embed field.value hard limit
STATS_WINDOWS_DAYS: tuple[int, ...] = (7, 30)
PID_FILE_PATH = "/tmp/teamode.pid"
DEFAULT_TIMEZONE = "America/Los_Angeles"

# ---------------------------------------------------------------------------
# Palette — UI-ADR § "Color palette"
# ---------------------------------------------------------------------------

COLOR_MATCHA_SAGE = "#7B9D6F"
COLOR_STEEPING_FOREST = "#3F5E4A"
COLOR_MUTED_GREY = "#8A8A8A"
COLOR_MUTED_RED = "#A05A5A"
COLOR_OOLONG_AMBER = "#C97B53"

# ---------------------------------------------------------------------------
# Existing copy — /teamode invocation guard (commands.py)
# ---------------------------------------------------------------------------

MSG_WRONG_CHANNEL = "Run `/teamode` from a voice channel's text chat."
MSG_NOT_IN_VOICE = "Join the voice channel first, then try again."
MSG_SESSION_ACTIVE = (
    "A TeaMode session is already running in this channel"
    " — please pick another text channel."
)

# Set-Intention participant prompt. ``{mentions}`` is "" when the voice
# channel has no non-bot members, or "<mention> <mention> " (note the
# trailing space) when it does — one template reproduces both call-site
# outputs byte-for-byte.
MSG_PARTICIPANT_PROMPT = (
    "🥅 **[Set Intention]** {mentions}Please share your intention "
    "for this session in voice or type it in the chat."
)

TEAMODE_COMMAND_DESCRIPTION = "Start a TeaMode focus session in this voice channel."
HANDOFF_COMMAND_DESCRIPTION = (
    "Transfer the facilitator role to another voice-channel member."
)
HANDOFF_MEMBER_DESCRIPTION = "The voice-channel member to make the new facilitator."

# /handoff guard refusals
MSG_HANDOFF_NO_SESSION = "No active TeaMode session in this channel."
MSG_HANDOFF_NOT_FACILITATOR = "Only the facilitator can hand off the role."
MSG_HANDOFF_SELF = "You are already the facilitator."
MSG_HANDOFF_TARGET_BOT = "Pick a human voice-channel member."
MSG_HANDOFF_TARGET_NOT_IN_VOICE = "Target must be in the voice channel."

# Manual /handoff, and automatic (facilitator-left-voice) handoff announcements.
HANDOFF_ANNOUNCE = (
    "<@{old_facilitator_id}> handed off — <@{new_facilitator_id}>,"
    " you're now the facilitator."
)
AUTO_HANDOFF_ANNOUNCE = (
    "<@{old_facilitator_id}> left — <@{new_facilitator_id}>,"
    " you're now the facilitator."
)

# ---------------------------------------------------------------------------
# Existing copy — welcome embed and timer-pick view (views.py)
# ---------------------------------------------------------------------------

WELCOME_EMBED_TITLE = "🍵 Now Entering TeaMode"
WELCOME_EMBED_DESCRIPTION = (
    "### Time for TeaMode!\n"
    "### · Grab your tea (or water/beverage of your choice),\n"
    "### · Clear your desk,\n"
    "### · And silence all distractions (like phones, impromptu meetings).\n\n"
    "### ⏳ **How long would you like to focus today?**"
)
TIMER_BUTTON_LABEL = "{minutes} min"

# ---------------------------------------------------------------------------
# Existing copy — intention modal and active timer message (views.py)
# ---------------------------------------------------------------------------

INTENTION_MODAL_TITLE = "Set your intention"
INTENTION_FIELD_LABEL = "What will you focus on?"

MSG_NOT_FACILITATOR = "Only the facilitator can answer."
MSG_VOICE_CONNECT_FAILED = "Could not join voice — session cancelled."

# Ephemeral refusal for a stale/finished-session component interaction —
# used for every stale button (timer pick, and any added later).
MSG_SESSION_INACTIVE = "This session is no longer active."

INTENTION_LINE_UNSET = "🍵 No intention set"

# ---------------------------------------------------------------------------
# Existing copy — end-of-session sequence (lifecycle.py)
# ---------------------------------------------------------------------------

END_EMBED_TITLE = "✨ Session complete!"
END_EMBED_BODY = "🌿 Sip your tea, stretch, and notice your progress."
END_OF_SESSION_MENTION = "Time's up, {mentions}!"
END_OF_SESSION_NO_MENTION = "Time's up!"

FOLLOWUP_PROMPT = "[Follow-up] React with ✅ if you finished, or ⛔ if not."
REFLECT_EMBED_TITLE = "🌿 [Reflect]"
REFLECT_EMBED_DESCRIPTION = (
    "### Share how your session went!\n"
    "### · React with emoji\n"
    "### · Share in voice\n"
    "### · Or type in chat"
)
FOLLOWUP_WHY_PROMPT = (
    "<@{facilitator_id}> — share what got in the way: type in chat or share in voice."
)

SOLO_GRACE_ENDED = "Session ended — facilitator did not return."

# ---------------------------------------------------------------------------
# New copy — voice channel status (used later)
# ---------------------------------------------------------------------------

VOICE_STATUS_STARTING = "🍵 Starting TeaMode"
VOICE_STATUS_TIMER = "⏳ to {hhmm}"
VOICE_STATUS_FINISHED = "✨ Finished TeaMode at {hhmm}"
VOICE_STATUS_CANCELLED = "🍵 Cancelled"
VOICE_STATUS_EXPIRED = "🍵 Expired"
VOICE_STATUS_CRASHED = "🍵 Crashed"
VOICE_STATUS_BREAK = "⏸️ Break until {hhmm}"

# ---------------------------------------------------------------------------
# New copy — timer embed (used later)
# ---------------------------------------------------------------------------

TIMER_EMBED_TITLE = "🍵 TeaMode • {duration} min session"
TIMER_FIELD_INTENTION = "Intention"
TIMER_FIELD_FACILITATOR = "Facilitator"
TIMER_FIELD_STARTED_AT = "Started at"
PHASE_DEEP_FOCUS = "Deep focus"
PHASE_WRAP_UP = "Wrap up — finish your current task"
TIMER_REMAINING = "{mmss} remaining"
TIMER_PROGRESS = "{bar} {percent}%"
TIMER_CONTENT = "⏳ {mmss} remaining"

# ---------------------------------------------------------------------------
# New copy — chaining and breaks (used later)
# ---------------------------------------------------------------------------

CHAIN_PROMPT = "Go again? / Take a 5-minute break?"
BUTTON_GO_AGAIN = "Go again"
BUTTON_BREAK = "Take a 5-minute break"
BREAK_STARTED = "⏸️ Break started — back at {hhmm}"
BREAK_OVER = "⏸️ Break is over"
BREAK_CANCELLED = "⏸️ Break cancelled by /teamode"

# ---------------------------------------------------------------------------
# New copy — refusals, nudge, expiry (used later)
# ---------------------------------------------------------------------------

MSG_RATE_LIMIT_USER = "Per-user rate limit — try again in {seconds} seconds."
MSG_RATE_LIMIT_GUILD = (
    "Daily server limit reached ({cap} sessions per day) — resets at midnight."
)
# Used for WRAP_UP_MINUTES >= 2 — see MSG_WRAP_UP_NUDGE_ONE for the 1-minute case.
MSG_WRAP_UP_NUDGE = "⏰ Wrap-up nudge — {minutes} minutes left."
MSG_WRAP_UP_NUDGE_ONE = "⏰ Wrap-up nudge — 1 minute left."
MSG_PENDING_EXPIRED = "🍵 Expired"

# ---------------------------------------------------------------------------
# New copy — /teamode-stats (used later)
# ---------------------------------------------------------------------------

STATS_COMMAND_DESCRIPTION = "Show TeaMode stats for you and this server."
STATS_TITLE = "🍵 TeaMode stats"
STATS_SECTION_YOU = "You"
STATS_SECTION_SERVER = "This server"
STATS_ROW_7D = "Last 7 days"
STATS_ROW_30D = "Last 30 days"
STATS_ROW_ALL = "All time"
STATS_ROW_VALUE = "{n} sessions · {minutes} min · {rate}% completed"
STATS_STREAK = "🔥 Streak: {days} days"
STATS_EMPTY = "No sessions yet — run /teamode to start one."

# ---------------------------------------------------------------------------
# New copy — /teamode-clear (used later)
# ---------------------------------------------------------------------------

CLEAR_COMMAND_DESCRIPTION = (
    "Delete past TeaMode messages in this channel (keeps timers)."
)
CLEAR_DONE = "🧹 Cleared {n} messages."
CLEAR_NOTHING = "Nothing to clear."
CLEAR_NO_PERMISSION = "You need the Manage Messages permission to run /teamode-clear."

# ---------------------------------------------------------------------------
# New copy — welcome banner (used later)
# ---------------------------------------------------------------------------

TEACUP_BANNER = (
    "     )  )\n"
    "    (  (\n"
    "   _______\n"
    "  |       |__\n"
    "  | TEA   |  )\n"
    "  |  MODE |_/\n"
    "   \\_____/\n"
    "  '-------'"
)
