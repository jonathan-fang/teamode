# Test Patterns — TeaMode (discord.py + asyncio)

Initial conventions for tests in this repo. Will be revised once the test
suite is large enough to surface real patterns. For now, these rules
prevent the most common discord.py testing pitfalls.

## Stack

- `pytest` — runner.
- `pytest-asyncio` — `@pytest.mark.asyncio` for coroutines; `mode = "auto"`
  in `pytest.ini` so awaitables don't need the decorator.
- `unittest.mock` — `patch`, `patch.object`, `AsyncMock`, `MagicMock`. No
  `monkeypatch`; sticking to one mocking system.
- `pytest-cov` — coverage when relevant; not blocking.

## Rules

### Test at boundaries, not against the Discord library

The boundary is the **bot module's public functions**: session lifecycle
(`start_session`, `end_session`), command handlers, and SQLite writes.
Don't test that discord.py emits the right gateway opcodes — that's
discord.py's job.

What to test:
- Session state transitions (`active` → `completed` / `crashed` /
  `cancelled` / `followup_timeout`).
- SQLite writes — schema columns populated correctly at each transition.
- Refusal logic — second `/teamode` in same channel rejects.
- Facilitator handoff selection — when multiple voice members remain,
  one is chosen.
- Voice channel guard — invocation outside voice is refused.

What not to test:
- That `interaction.response.send_message` was called with exact args at
  the discord.py level — couples tests to the library.
- That `ffmpeg` produced bytes — environmental and slow.

### Mock the Discord interaction surface

Build a tiny `FakeInteraction` (or `AsyncMock`-based fixture) that exposes
just the attributes our code reads: `user.id`, `guild.id`,
`channel.id`, `user.voice.channel`, `response`, `followup`. Treat it as
the seam between our code and Discord. Tests should never hit a live
Discord gateway.

```python
# tests/conftest.py (sketch)
@pytest.fixture
def fake_interaction():
    inter = AsyncMock()
    inter.user.id = 111
    inter.guild.id = 222
    inter.channel.id = 333
    inter.user.voice.channel.id = 333  # same as text chat — voice channel's text
    return inter
```

### Use `AsyncMock` for awaitables

`MagicMock()` returns a MagicMock from `await mock()`, which silently
breaks async paths. Reach for `AsyncMock` whenever a coroutine is mocked.

### `freezegun` or injected clock for time-sensitive tests

Countdown logic depends on real time; tests must not. Either inject a
clock function (`time_fn=time.monotonic` default) or use `freezegun`. Pick
one approach per file and stay consistent.

### SQLite tests use a real in-memory database

`sqlite3.connect(":memory:")` is fast and exercises the real query path.
Do not mock the SQLite layer — mocking persistence layers that can be
exercised directly is forbidden by `.project-meta/conventions.md`.

```python
@pytest.fixture
def in_memory_db():
    conn = sqlite3.connect(":memory:")
    conn.execute(SCHEMA_SQL)  # imported from teamode.db
    yield conn
    conn.close()
```

### Patch where the function is *used*, not where it's defined

Standard mocking gotcha. If `teamode.session` does `from .db import
write_session_row`, tests must patch `teamode.session.write_session_row`,
not `teamode.db.write_session_row`. The same convention is in
`.project-meta/conventions.md` §Testing — it survived for a reason.

### Don't test invariants you don't actually rely on

A test that asserts "function X calls Y with exact arg Z" mirrors the
implementation. A test that asserts "the side effect Y must occur
regardless of internal routing" captures the contract. Prefer the
latter — it survives refactors.

## Decision Matrix

| Situation | Pattern |
|-----------|---------|
| Same fixture across 3+ test files | `conftest.py` fixture |
| Same fixture across 2 test files | per-file helper in each (don't share yet) |
| Setup unique to one test | inline `with patch(...)` |
| Awaitable being mocked | `AsyncMock` |
| Time-sensitive code | injected clock or `freezegun` |
| Discord gateway interaction | `FakeInteraction` fixture |
| SQLite write/read | `:memory:` connection — no mock |
| Voice playback | mock `voice_client.play`; assert it was called with the right `FFmpegPCMAudio` source path |

## What Not To Do

- **Don't hit a live Discord gateway** in any test, ever. Even if rate
  limits would forgive it, tests must be hermetic.
- **Don't shell out to `ffmpeg`** in tests. Mock the voice client.
- **Don't build deep `AsyncMock` chains** to satisfy library internals.
  If a test requires `inter.followup.send.return_value.edit.return_value...`
  with three levels of mock, the seam is wrong — refactor the production
  code so the test exercises a smaller surface.
- **Don't introduce `monkeypatch`** alongside `patch` / `patch.object`.
  One mocking system per repo.

## When this file is wrong

Revise it. If the suite reveals a pattern (an `AsyncMock` fixture used
across 5 files, a SQLite seed helper duplicated 3 times), promote it to a
fixture and update this guide. Don't preserve a rule because it's written
down — preserve rules that pay rent.
