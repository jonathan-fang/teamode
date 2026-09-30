# External Interest Log

Tracks outside interest in trying/hosting TeaMode — not product work,
just a record for if/when it resurfaces.

## Megan — May 2026

Floated running TeaMode for Megan to try (bot had been in personal use
~2–3 weeks as of 2026-05-10; free-tier hosting like AWS considered).
**Resolved: not interested at this time.** Revisit if interest comes
back up — see `docs/groove-boogaloo-deployment.md` for the actual
external-server deployment path when that becomes relevant.

## Postponed pending external interest — 2026-09-29

The following were postponed as sole-user overkill: they only earn their
complexity if TeaMode gets a second user/server. Revisit any of these if
that changes.

- **Intention text privacy.** Restricting intention-text persistence to a
  developer allowlist, or making it opt-in/stripped for non-developer
  accounts. Only matters once someone other than the developer is running
  sessions.
- **Data anonymization (Option B).** Dropping `facilitator_id` /
  `handoff_facilitator_id` in favor of an aggregate-only `stats` table.
  The decision itself is already made and documented in
  `docs/groove-boogaloo-deployment.md` if this comes back up — just not
  worth implementing while there's one user and no external server.
- **Shareable to one external server.** README + token + slash-command
  registration walkthrough so a colleague can clone, configure, and run
  on their own server within 30 minutes.
- **VPS hosting path.** Deploy guide + systemd unit + secrets handling
  for always-on operation. Would follow the external-server item above.
- **Participant capture.** The MVP keeps participant intentions/follow-
  ups social-only (prompted, not logged). Two options were scoped if this
  becomes worth building: (1) chat-window listener — bot listens for chat
  messages from voice members during a 60s window, needs Message Content
  Intent + a participants table; (2) per-user "Share my intention" modal
  button — no extra intent needed, cleaner privacy story. Both blocked on
  the same question: is look-back participant data actually useful with
  more than one user in the loop.

## Donations & legal requirements — resolved, filed for later

Already researched in full in `docs/groove-boogaloo-deployment.md` §
"Donations & Legal Requirements (US)". Short version: Ko-fi on a personal
account, no business entity needed, nothing to act on below ~$200/year
in tips. Only relevant once a real hosting cost exists (i.e. once this
moves off a personal machine — see the external-server items above).

## Hosting research — Cloudflare Workers vs. a VM

Looked into whether Cloudflare Workers could host TeaMode for free.
**Conclusion: no, not for this bot.** Workers are stateless/serverless —
they spin down between requests and cap each invocation at ~10ms CPU —
so they can't hold the persistent voice-channel WebSocket connection or
play audio in voice at all. Cloudflare only fits bots that are pure
slash-command/button/modal interactions with no voice component, which
isn't TeaMode. If/when hosting moves off a personal machine, a
traditional always-on VM (e.g. Oracle Cloud's free tier) is the right
free-tier fit — this is the same conclusion `docs/language-library-
comparison.md` § "Hosting options" already reaches. Filed here since it
only matters once the "Shareable to one external server" item above is
active.
