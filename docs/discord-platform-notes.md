# Discord Platform Notes

Reference findings from `docs.discord.com/developers/`. Covers only what the
TeaMode bot needs: slash commands, interactive components, voice audio
playback. Not a comprehensive Discord guide.

---

## Slash Commands (`/teamode`)

**Registration**
- **Guild-scoped** during dev: instant updates, scoped to one server. Use this
  for the personal MVP.
- **Global**: 100-command app limit, propagates over up to ~1 hour.
- POST to `/applications/{app_id}/guilds/{guild_id}/commands` (guild) or
  `/applications/{app_id}/commands` (global) with `name`, `description`,
  `options`.

**Option types** (11 total): string, integer, boolean, user, channel, role,
number, attachment, mentionable, subcommand, subcommand-group.
- `choices` (max 25) restricts input to a fixed set — fits the timer-duration
  picker if exposed as a command option, but we plan to use a button row
  instead so the prompt is conversational rather than at-invocation.

**Response timing — hard limit**
- Initial response **must** be sent within **3 seconds** of the interaction
  arriving. Exceeding it silently invalidates the interaction token.
- For anything that takes longer (countdown, async work), send a **deferred
  response** (`DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE`, type 5) immediately, then
  follow up within **15 minutes** via the interaction token.
- Follow-up messages can be sent repeatedly using the same token; each can be
  edited.

**Ephemeral flag**: per-message, makes the message visible only to the invoking
user. Useful for private follow-up prompts ("Did you accomplish your
intention?"). The shared timer message itself should be non-ephemeral so
co-workers in the voice channel can see it.

---

## Components

**Buttons** (the primary UI for our step flow):
- Styles: Primary (blurple), Secondary (grey), Success (green), Danger (red),
  Link, Premium.
- Up to **5 buttons per Action Row**, up to **5 rows per message**, **40
  components total**.
- Each button has a `custom_id` (1–100 chars, unique per message). The
  interaction handler dispatches on this id.

**Select menus** (one per Action Row): String, User, Role, Mentionable,
Channel. Probably overkill for TeaMode — three timer options fit on one button
row.

**Modals**: form-style popups. A candidate for the "intention" input — keeps
typing private (modal text is only seen by the submitter) without needing an
ephemeral chat reply. Tradeoff: the intention won't be visible to co-workers.
Decision deferred to Round 2.

**`custom_id` pattern**: design a namespacing scheme up front so a single
interaction handler can dispatch (e.g. `teamode:timer:25`,
`teamode:followup:yes`). Bake the session id in for multi-session safety
(`teamode:<session_id>:timer:25`).

---

## Voice Audio Playback (the `reverie.wav` ring)

Joining a voice channel and playing audio is **non-trivial**. The protocol:
gateway voice state update → voice server info → second WebSocket → UDP
socket → Opus-encoded RTP packets, encrypted.

In practice, the library handles this. What the bot environment needs:
- **discord.py / py-cord**: `PyNaCl` (encryption) + `ffmpeg` binary on PATH +
  Opus library (libopus, usually bundled or system-installed). Voice support
  is optional install: `pip install "discord.py[voice]"`.
- **discord.js**: `@discordjs/voice` + `@discordjs/opus` (or `prism-media`) +
  `sodium` (or `tweetnacl`) + `ffmpeg`.

**Bot must be in the voice channel to play audio.** TeaMode's facilitator
flow: when `/teamode` is invoked from a text channel and the invoker is in a
voice channel, the bot joins that voice channel. If not, the bot can only post
text/notification — the audio ring is skipped (graceful degradation) or
refused (require voice — TBD in Round 2).

**Alternative for getting attention without voice**:
- **`@mention`** the facilitator in a follow-up message → standard Discord
  notification (sound + badge).
- **Visual**: a large emoji burst, a colour-styled embed, or a sequence of
  edits that flash a banner.
- **Voice playback** (preferred when the facilitator is in voice): the
  `reverie.wav` plays through everyone's headphones in the channel — the most
  attention-grabbing option and the closest fit to the dlqa focuswork
  experience.

---

## Rate Limits & Gotchas

- Discord enforces per-route and global rate limits. Sustained ignoring →
  token revocation. The library handles this with backoff; don't bypass.
- All snowflake ids returned as **strings** to avoid 64-bit integer overflow
  in JS clients — preserve string typing throughout.
- Signed CDN URLs expire; refresh by re-fetching the message rather than
  caching the URL.
- Message content intent: as of 2022, reading message text in non-DM channels
  requires the **Message Content Intent** to be enabled in the bot's
  application settings *and* requested at gateway connect. Slash commands and
  component interactions do **not** require it — they deliver payloads
  directly. **TeaMode interaction model is purely slash + buttons + modals**,
  so we do not need Message Content Intent. This simplifies bot approval if
  ever distributed.

---

## Source links

- `https://docs.discord.com/developers/reference` — auth, snowflakes,
  versioning, rate limits.
- `https://docs.discord.com/developers/interactions/application-commands` —
  slash command registration and response.
- `https://docs.discord.com/developers/components/reference` — buttons,
  selects, modals.
- `https://docs.discord.com/developers/topics/voice-connections` — voice
  protocol.
