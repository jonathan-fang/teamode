# Discord Bot Setup — TeaMode (Ocha)

What to configure on the Discord developer portal so `python3
teamode.py` can connect and run a session end-to-end. This is a
one-time setup per Discord application.

Assumes you have already:
- Created a Discord application named `TeaMode` (developer portal).
- Read Discord's Developer Terms and Developer Policy.

## 1. Bot user

In the application's left sidebar, **Bot** → **Add Bot**.

- **Username:** `Ocha` — this is the chat-visible name the bot
  appears as in messages.
- **Public Bot:** OFF for personal use (only you can add it to
  servers).
- **Requires OAuth2 Code Grant:** OFF.

Click **Reset Token** and copy the token immediately — Discord shows
it once. This is `DISCORD_BOT_TOKEN`. Store it in a local `.env` file
or your shell environment; never commit it.

## 2. Privileged Gateway Intents

Same **Bot** page, scroll to **Privileged Gateway Intents**:

| Intent | Setting | Why |
|---|---|---|
| Presence Intent | OFF | Not used. |
| Server Members Intent | OFF (MVP) | Only required for Stage 5 facilitator-handoff RNG over the full member cache. The MVP iterates over `VoiceChannel.voice_states` instead, which does not need this intent. Re-enable if Stage 5 hits a cache miss. |
| Message Content Intent | OFF | The bot does not read user message content — participant prompts are advisory ("type your intention in chat or share it in voice"); nothing is parsed or persisted. |

Leaving privileged intents off keeps the verification bar low (under
75 servers, no Discord review required).

## 3. Bot permissions

Permissions are requested at invite time via the URL generator (next
section). The bot needs:

| Permission | Why |
|---|---|
| View Channels | See voice channels and their text chats. |
| Send Messages | Post welcome embed, timer, follow-up. |
| Embed Links | Render embeds (the welcome / end-of-session surfaces). |
| Read Message History | Lets the bot resolve message references for edits. |
| Use Application Commands | Slash commands (`/teamode`). |
| Add Reactions | Bot does not add reactions itself (participants do), but having this enabled future-proofs Stage 4 polish. |
| Connect | Join the facilitator's voice channel. |
| Speak | Play `assets/reverie.wav` at session end. |

**Permissions integer:** `2150714432` — paste this into the URL
generator's "Permissions" field, or check the boxes individually.

The bot does **not** need: Administrator, Manage Channels, Manage
Server, Mention Everyone, Send TTS, Manage Messages, Manage Roles,
Move Members, Mute Members, Deafen Members, or any moderation
permission.

## 4. OAuth2 invite URL

In the application sidebar, **OAuth2** → **URL Generator**.

- **Scopes:** `bot` and `applications.commands`. Both are required —
  `bot` to add the user to a guild, `applications.commands` so the
  slash command can register.
- **Bot Permissions:** check the boxes from the table above (or paste
  the integer).
- Copy the generated URL, open it in a browser, pick your dev guild,
  authorize.

## 5. Dev guild id

For instant slash-command propagation during development, register
`/teamode` to a single guild instead of globally. Global commands take
up to one hour to propagate; guild-scoped is instant.

In Discord (with Developer Mode on under User Settings → Advanced):
- Right-click your dev server in the server list → **Copy Server ID**.
- Set as `TEAMODE_DEV_GUILD_ID` in your `.env` or shell.

If `TEAMODE_DEV_GUILD_ID` is unset the bot starts but skips command
registration with a warning — by design.

### Private voice channels

Discord evaluates permissions in order: role grants → channel
overrides → category overrides, with denies winning. In a public
channel, `@everyone` has View Channel by default, so a role with
View Channel granted just works. In a **private** voice channel,
`@everyone` is denied View Channel by default, and role-level grants
do **not** propagate. You must explicitly add the `TeaMode` role (or
the Ocha bot user directly) to the channel's allow-list — at the
voice channel's settings → Permissions → Add role/member → grant
View Channel, Connect, Speak, Send Messages, Embed Links, Add
Reactions, Use Application Commands. (The application-level perms
integer from § 3 covers the role grant; the channel override grants
the role access to *this specific channel*.) The bot itself cannot
detect or work around this — it just gets `403 Forbidden` from the
Discord API.

## 6. Local `.env`

Sample `.env` at the repo root (gitignored):

```
DISCORD_BOT_TOKEN=<your-bot-token>
TEAMODE_DEV_GUILD_ID=<your-dev-guild-id>
TEAMODE_DB_PATH=./sessions.db
```

`.env.example` carries stub values only — never commit a real token.

## 7. Run

```bash
cd ~/WSL/github.com/jonathan-fang/teamode
source .venv/bin/activate
python3 teamode.py
```

You should see:
- A startup line with the bot user and id.
- A "Slash commands synced to guild …" line.

Then in your dev guild, `/teamode` should be available immediately
when invoked from a voice channel's text chat.

## What changes for V2 (deployment, not now)

If we later promote to a Linux VPS or make the bot installable on
other servers:
- Flip Public Bot ON.
- Drop `TEAMODE_DEV_GUILD_ID` and let commands register globally
  (accept the propagation delay).
- Re-evaluate Server Members Intent if Stage 5 needs the full cache.
- Consider Discord verification once over 75 servers.
