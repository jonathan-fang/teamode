---
title: TeaMode v26Q3.0.0.0
---

# APM Tracker

## Task Tracking

**Stage 1:** Complete

**Stage 2:** Complete

**Stage 3:**

| Task | Status | Domain | Branch |
|------|--------|--------|--------|
| 3.1 | Done | bot-engineer | |
| 3.3 | Done | bot-engineer | |
| 3.2 | Active | bot-engineer | feat/voice-channel-status |

## Version Control

| Repository | Base Branch | Branch Convention | Commit Convention |
|-----------|-------------|-------------------|-------------------|
| teamode | main | `type/short-description`, `--no-ff` merge, delete after merge, no push | Conventional Commits `type(scope): desc`, 50/72, no attribution trailers |

## Working Notes

- 3.1 smoke passed (1–7 incl. mobile, embeds-off, solo grace). User set NUDGE_MIN_DURATION_MINUTES=10 (Spec updated). Task 3.3 added: singular nudge copy, wind-chime in voice with nudge (assets/wind-chime.wav copied from user's Downloads, 3.4 s PCM), nudge deleted at terminal cleanup, content line '⏳ MM:SS remaining'. Merge of feat/embed-timer waits for 3.3 + re-check.
- 3.3 reviewed OK (dd0f517, ebf82f2, 18800b5; 223 tests): `voice.play_wind_chime(vc) -> bool`, `timer_format.format_wrap_up_nudge`, `_SetupMessages.nudge_message_id`.
- User re-check of 3.3 passed (1–4). Manager added `TIMER_TIME_RANGE = "{start} to {end}"` (User-specified) for the Started at field — e06bc57, 224 tests. Sound credits recorded in Spec §Documentation (README). Repo is private.
- User: field label 'Range' (TIMER_FIELD_RANGE, d1d0bb3); README credit for reverie must NOT mention/link Stretchly (Spec updated). Role permission Set Voice Channel Status granted by User.
- Restored DURATIONS_MINUTES=(5,10,25,50) when committing User's constants comments (d: chore(constants)) — told User.
- feat/embed-timer merged as 0970a4d (User-approved). User's smoke values (DURATIONS 2-min, WRAP_UP 1, NUDGE_MIN 1) still uncommitted in app/constants.py — never stage them; stash around branch switches.
- Planned dispatches remaining: 3.2 (active) (single — permission decision point), 4.1, 4.2, 5.1+5.2, 5.3, 6.1.
- 3.1 prompt decisions to surface at smoke: phase/countdown/progress in embed description with `### ` prefix (UI-ADR content-embed rule); progress = elapsed fraction, floored; solo-grace final state = content text + frozen embed recolored muted red; mention line kept on content edits (consistent with 2.4).
- 5.1 and 5.2 dependency-Ready, held for slip priority (Stage 5).
- Test hygiene leftover: ~6 "coroutine never awaited" warnings (mocked create_task vs spawn_logged) — fold into 6.1 or TODO.md.
- `.claude/` left untracked (pre-existing state).
