# TeaMode SQLite Schema (Proposed)

One table for v1: `sessions`. Rationale: each `/teamode` invocation produces
exactly one row, written once at session start and updated as state advances
(intention captured, timer ends, follow-up answered or timed out). Adequate
for the look-back use case (intentions, follow-ups, completion stats) without
introducing relational complexity prematurely.

If we later track participants individually (who reacted to follow-up, who
was in voice), promote to a second table `session_participants` keyed by
`session_id`. Out of scope for MVP.

---

## `sessions` table

```sql
CREATE TABLE sessions (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id             TEXT    NOT NULL,
    text_channel_id      TEXT    NOT NULL,
    voice_channel_id     TEXT    NOT NULL,
    facilitator_id       TEXT    NOT NULL,
    started_at           TEXT,
    duration_minutes     INTEGER,
    intention            TEXT,
    ended_at             TEXT,
    completed_intention  INTEGER,
    followup_note        TEXT,
    status               TEXT    NOT NULL,
    handoff_facilitator_id TEXT
);

CREATE INDEX idx_sessions_facilitator ON sessions(facilitator_id);
CREATE INDEX idx_sessions_started_at  ON sessions(started_at);
```

---

## Field-by-field reference

### `id`
Local primary key. Not a Discord id — just an autoincrement for our own
joins and references. No Discord meaning.

### `guild_id` — Discord Guild ID
The Discord server the session was started in. A "guild" is Discord's
internal name for a server.

- **Type**: snowflake string.
- **Why string?** Discord snowflakes are 64-bit integers; some languages
  (notably JavaScript) cannot represent them precisely as numbers. The API
  always returns them as strings. We store as TEXT to match — no precision
  loss, no platform surprises.
- Source: `https://docs.discord.com/developers/reference` — "Snowflakes are
  returned as strings in JSON responses."

### `text_channel_id` — Discord Channel ID
The text channel `/teamode` was invoked from. Per the invocation rule, this
is the text-chat-attached-to-a-voice-channel (Discord voice channels carry
their own text chat).

- **Type**: snowflake string.
- **Reason to store**: enforces the "one session per text channel" rule —
  on `/teamode` invocation, query for any session in this `text_channel_id`
  with `status = 'active'`; if found, refuse politely.
- Source: `https://docs.discord.com/developers/resources/channel` — channel
  ids are snowflakes.

### `voice_channel_id` — Discord Voice Channel ID
The voice channel the facilitator was in when invoking. The bot joins this
channel to play `reverie.wav` at session end.

- **Type**: snowflake string.
- **Why separate from text_channel_id**: although Discord voice channels
  have associated text chat, the channel id of that text chat is *the same*
  as the voice channel's id (a voice channel exposes both surfaces under one
  id). Storing separately is defensive — if Discord ever splits them again,
  the schema still holds. For MVP they will be equal.
- Source: `https://docs.discord.com/developers/topics/voice-connections` —
  bot joins by guild id + channel id.

### `facilitator_id` — Discord User ID
The user who invoked `/teamode`. Discord exposes this on the interaction
payload as `interaction.user.id`.

- **Type**: snowflake string.
- **Reason to store**: stats ("how many sessions have I run?"), and to
  identify when the facilitator leaves voice mid-session (compared against
  the voice channel's current member list).
- Source: `https://docs.discord.com/developers/interactions/receiving-and-responding`
  — interaction object has `user` field.

### `started_at`
ISO-8601 UTC timestamp at the moment the timer was confirmed and started
(after the facilitator selected duration and entered intention).

- **Type**: TEXT (SQLite has no native datetime type; ISO-8601 sorts
  lexicographically).
- **Format**: `YYYY-MM-DDTHH:MM:SS.sssZ` — produced by
  `datetime.now(timezone.utc).isoformat()`.
- **Nullable** until the `active` transition. While the row is in
  `pending` or `intention_set` the timer has not yet started, so this
  column is NULL.

### `duration_minutes`
The chosen timer length: 10, 25, or 50 for MVP.

- **Type**: INTEGER.
- **Validation**: enforced at choice-time (button options) — not a free
  field.
- **Nullable** until the facilitator picks a duration. While the row is
  in `pending` this column is NULL.

### `intention`
Free text the facilitator typed into the modal, e.g. "Finish the v26Q2.2.0
changelog." Empty string allowed (intention is optional in the flow).

- **Type**: TEXT, nullable until intention step completes.
- **Length cap**: Discord modal text inputs cap at 4000 chars; we store
  whatever is submitted.
- Source: `https://docs.discord.com/developers/components/reference` —
  Text Input component, max length 4000.

### `ended_at`
ISO-8601 timestamp when the session reached a terminal state (timer
completed, follow-up answered or timed out, session marked crashed/cancelled).
Nullable while the session is active.

### `completed_intention`
The yes/no answer to the follow-up question.

- **Type**: INTEGER (SQLite booleans). `1` = yes, `0` = no, `NULL` =
  follow-up timed out without an answer or facilitator left.

### `followup_note`
Optional text the facilitator typed when answering "No" — the *why* of an
unmet intention. Nullable.

- **Type**: TEXT.

### `status`
Current state of the session. Enum of:
- `pending` — `/teamode` invocation accepted; awaiting timer-pick.
- `intention_set` — duration picked and intention captured; bot is
  about to join voice and start the timer.
- `active` — timer is running.
- `followup` — timer reached zero; awaiting facilitator Y/N answer.
- `completed` — timer finished and follow-up answered.
- `followup_timeout` — timer finished but follow-up was not answered within
  3 minutes.
- `crashed` — bot process died mid-session (set by next-startup
  reconciliation; see "Bot reconnect / process restart" below).
- `cancelled` — facilitator left and never came back; or facilitator
  explicitly cancelled (out of MVP).

- **Type**: TEXT (cheap enum). A CHECK constraint can enforce the values
  but is not required for MVP.

### `handoff_facilitator_id`
If the original facilitator left voice mid-session and another participant
took over, this records the new facilitator's user id. Nullable when no
handoff occurred.

- **Type**: snowflake string.
- **Reason to store**: lets the look-back stats distinguish "ran a full
  session" from "took over a session" without altering the original
  `facilitator_id` field.

---

## What's intentionally **not** stored

- **Participant list at start**: would require a `guild.voice_states`
  snapshot at invocation time. Adds API call complexity for a stat we don't
  yet need. Defer to v2.
- **Reaction details on the follow-up**: only the facilitator's answer is
  authoritative for `completed_intention`; co-worker reactions are social
  signal, not state. If we want to count "participants who reacted",
  promote to a `session_reactions` table later.
- **Per-tick countdown samples**: no history of timer edits. The timer is
  ephemeral by definition.

---

## Source links

- `https://docs.discord.com/developers/reference` — snowflake format.
- `https://docs.discord.com/developers/interactions/application-commands`
  — slash command interaction payload.
- `https://docs.discord.com/developers/interactions/receiving-and-responding`
  — interaction object structure.
- `https://docs.discord.com/developers/components/reference` — text input
  4000-char limit.
- `https://docs.discord.com/developers/topics/voice-connections` — voice
  channel join semantics.
