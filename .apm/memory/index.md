---
title: TeaMode v26Q3.0.0.0
---

# APM Memory Index

## Memory Notes

- User approves in terse replies ("y"). Every merge into `main` needs an explicit User "y" after seeing commits + changed files; Workers commit freely on feature branches. Task Prompts should state "commit freely on your branch" explicitly — one Worker misread the Rules and withheld a commit.
- Dispatch is foreground and sequential (User preference; parallel worktrees were costly in the MVP). Agent calls nonetheless run as background tasks in this environment — wait for the completion notification before reviewing.
- `ruff` and `pyright` live only in `.venv/bin`; Task Prompts must tell Workers to `source .venv/bin/activate` first.
- `app/discord_bot/` uses mixin composition: `TeaModeBot(CommandsMixin, ViewsMixin, TimerMixin, LifecycleMixin)` in `client.py`. Each mixin declares the `self` attributes it reads as type-only class annotations; cross-mixin typing uses structural Protocols (e.g. `_ModalBot` in `views.py`) with `TYPE_CHECKING`-guarded stubs — never `cast()`.
- Test fakes for channels must be spec'd (`AsyncMock(spec=discord.TextChannel)` / `MagicMock(spec=discord.VoiceChannel)`) because production code now narrows with `isinstance`; unspec'd mocks silently fail narrowing. Interaction fakes must set `channel_id` explicitly.
- All Discord copy and tunables live in `app/constants.py` (all canonical copy for later features already present, verbatim). Old private `_MSG_*` / `_*_SECONDS` names no longer exist; tests import from `app.constants`.
- Rate limit decision: allowance 3 per 300 s window, 4th refused (User confirmed over TODO.md wording).

## Stage Summaries

### Stage 1 - Foundation: Tooling, Package Split, Constants, Typing

Stage 1 completed in two Bot Engineer batches, each on its own branch, both merged `--no-ff` after User approval (`14c2c2c` for `refactor/discord-bot-package`, then `refactor/constants-and-typing`). The first batch added explicit pyright/Ruff config (`1d1cb65`) — pyright was in fact already clean before config, contrary to the planning assumption — and split the 1038-line `app/bot.py` into `app/discord_bot/` using mixins (`38a5cef`); pyright's per-mixin analysis required type-only attribute declarations on each mixin. The second batch created `app/constants.py` with every tunable, palette hex value, existing string (inventory larger than planned: handoff copy, Time's up, Reflect, "why" prompt) and all new canonical copy including `TEACUP_BANNER` with an exact-lines test, plus duration-pick validation (`fad6354`); then enabled Ruff `ANN` (no violations — code was already annotated) and removed all 13 cast/ignore occurrences, including one the split introduced, via isinstance narrowing, `channel_id`, a `None` guard on `lastrowid`, and a `_ModalBot` Protocol (`9b5e562`, committed by the Manager because the Worker misread the approval rule). Test fixtures were corrected to spec'd mocks without assertion changes. Suite grew from 122 to 125 tests; all five checks clean. The User ran the end-of-Stage Discord session check on the branch before approving the merge.

**Task Logs:**
- task-01-01.log.md
- task-01-02.log.md
- task-01-03.log.md
- task-01-04.log.md
