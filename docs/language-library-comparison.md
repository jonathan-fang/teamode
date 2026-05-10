# Language / Library Comparison for TeaMode

Pros and cons of the four serious candidates for the bot framework, evaluated
against TeaMode's specific needs:

- Single command (`/teamode`), button-driven step flow, modal for intention.
- A countdown timer with per-second updates (or banded edits to avoid rate
  limits).
- Voice channel audio playback (`reverie.wav` at session end).
- Session log persistence (intentions, follow-ups, completion stats).
- Self-hostable by a non-developer eventually (one-server distribution).

---

## 1. discord.py (Python)

**Pros**
- **Stack alignment** with `dlqa` and `dawa`: both are Python projects with
  ruff + pyright + pytest tooling per `.project-meta/conventions.md`. Reusing
  the same toolchain means the existing validation gates and code-style rules
  port directly.
- The dlqa focuswork countdown pattern (`_run_countdown` in
  `app/ui/runtime_flow.py`) is conceptually portable — a worker thread
  ticking once per second, posting UI updates via a thread-safe bridge. The
  Discord analogue is `asyncio.sleep(1)` in a coroutine + `message.edit()`.
- Mature, idiomatic API. `app_commands` covers slash commands; `discord.ui`
  covers buttons / selects / modals as Python classes.
- Voice support via `pip install "discord.py[voice]"` (PyNaCl + ffmpeg
  binary). Plays WAV/MP3 through `FFmpegPCMAudio`.
- Rapptz/discord.py was unpaused in 2021 and is actively maintained again as
  of 2025. Forks (`py-cord`, `nextcord`) are also maintained, but main-line
  discord.py is the safe default.
- Reverie.wav lives in the dlqa repo today and is a stock WAV file —
  no special handling.

**Cons**
- `asyncio` model — different mental shift from dlqa's threading model. The
  countdown coroutine runs in the event loop, not a worker thread. A small
  adjustment, not a real obstacle.
- Slightly less performant under massive scale than Node, but irrelevant for a
  one-server bot.

---

## 2. py-cord (Python, fork of discord.py)

**Pros**
- API is ~95% identical to discord.py. Slash commands and components are
  arguably *slightly* nicer (less ceremony around CommandTree).
- Was the recommended path during the discord.py pause; many tutorials still
  reference it.

**Cons**
- Smaller community than discord.py post-resumption. New Discord API features
  sometimes land later.
- No advantage for our use case over mainline discord.py.

**Verdict**: viable, but mainline discord.py is the safer pick now that it's
back in active development.

---

## 3. discord.js (Node.js / TypeScript)

**Pros**
- Largest community, most third-party hosting tutorials, biggest ecosystem
  (PomPom, Pomomo, and most of the existing pomodoro bots use it).
- Strong typing via TypeScript if used with `@types/discord.js` and `tsc`.
- Slightly better performance ceiling (irrelevant for one server).

**Cons**
- **Stack mismatch.** `dlqa` and `dawa` are Python; conventions are
  Python-tooling-specific (ruff, pyright, pytest, `requirements.txt`).
  Adopting Node introduces a parallel toolchain (eslint, prettier, jest,
  package.json, node_modules) with no shared conventions. The convention doc
  would need a TypeScript supplement.
- Voice setup is heavier: `@discordjs/voice` + opus codec + sodium +
  ffmpeg — more moving parts than the Python equivalent.
- No reuse of dlqa patterns. Countdown UI logic, persistence helpers, audit
  patterns all rewritten from scratch.

**Verdict**: technically strong but loses the integration value with the
existing project family.

---

## 4. nextcord (Python, fork of discord.py)

**Pros**
- Another active fork. Feature set similar to py-cord.

**Cons**
- Smaller community than both discord.py and py-cord. No tangible advantage.

**Verdict**: skip unless a specific feature it has is needed.

---

## Recommendation

**discord.py.**

Reasoning:
1. **Toolchain fit**: ruff, pyright, pytest, `requirements*.txt` already have
   conventions in `.project-meta/conventions.md`. TeaMode inherits these for
   free.
2. **Code reuse pattern**: dlqa's countdown loop, log patterns, and threading
   bridge translate to Discord's async model with minimal cognitive load.
3. **Active maintenance**: Rapptz/discord.py is back in active development;
   the historical reason for moving to py-cord is no longer load-bearing.
4. **Voice path is well-trodden**: `discord.py[voice]` + ffmpeg + a stock WAV
   is a one-page setup.
5. **Distribution path** (post-MVP, share with one other server): a thin
   README + bot token + slash command registration step. No more friction in
   Python than in JS.

Confirmation needed before locking this in — Round 2 question.

---

## Open question

If you have a strong preference for Node — e.g. you want the bot to power a
web dashboard later — flag it. Otherwise discord.py is the default.
