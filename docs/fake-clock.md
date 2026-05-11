# FakeClock — testing time-dependent async code

A test seam for `app.session.run_countdown` (and any future timer-like
coroutine). Lets a test fast-forward simulated minutes in microseconds
without real waits, while still asserting tick cadence and edit
cadence.

## Why

`run_countdown` takes two callables as parameters with sensible
defaults:

```python
async def run_countdown(
    *,
    duration_minutes: int,
    on_tick: Callable[[int], Awaitable[None]],
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> None:
```

Production passes the real `asyncio.sleep` and `time.monotonic`. Tests
substitute a fake pair so a 25-minute countdown finishes in test time
proportional to the number of iterations, not to wall time.

## Shape

```python
class FakeClock:
    def __init__(self) -> None:
        self.now: float = 0.0

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds
        # No real await — return immediately.
```

`now` advances by exactly the requested sleep duration. `monotonic`
reads it back. The combination drives any drift-corrected loop that
computes `next_target = start + tick_index * interval` and sleeps
`max(0, next_target - monotonic())`.

## Use

```python
fake = FakeClock()
ticks: list[int] = []

async def on_tick(seconds_remaining: int) -> None:
    ticks.append(seconds_remaining)

await run_countdown(
    duration_minutes=1,            # 60 seconds
    on_tick=on_tick,
    sleep=fake.sleep,
    monotonic=fake.monotonic,
)

assert len(ticks) == 61                # seconds 60, 59, …, 1, 0
assert fake.now == pytest.approx(60.0)
```

Asserting both the tick count and the elapsed `fake.now` catches
two classes of regression at once: missing or extra ticks, and any
drift in the sleep-target calculation.

## Edit-cadence assertion

The countdown ticks every second, but the active-timer message edits
every 10 seconds (per Spec § "UI Surface — Edit cadence rules"). To
test that, count edit-eligible ticks separately:

```python
edits = [s for s in ticks if s % 10 == 0]   # 60, 50, 40, 30, 20, 10, 0
assert len(edits) == 7
```

## Testing drift correction

Inject a `sleep` that adds extra wall time per call to simulate load:

```python
class LaggyFakeClock(FakeClock):
    async def sleep(self, seconds: float) -> None:
        self.now += seconds + 0.05      # 50ms artificial lag per tick
```

Then assert that the next sleep target compensates — `fake.now` after
the full countdown should still be within tolerance of
`duration_minutes * 60`, because `run_countdown` recomputes the target
from the original start time, not from the previous tick.

## What FakeClock is not

- **Not a mock of `asyncio.sleep` globally.** It only intercepts the
  callable explicitly passed to `run_countdown`. Other `asyncio.sleep`
  calls (e.g. inside discord.py's HTTP layer) still use the real
  loop — which is correct, because `run_countdown` is the unit under
  test, not discord.py.
- **Not a `pytest-asyncio` event-loop replacement.** The test still
  runs on a real event loop; only the simulated time is fake.
- **Not a `freezegun`-style patch.** Nothing patches `time.monotonic`
  or `asyncio.sleep` globally — the seam is dependency injection
  through the function signature.

## Where it lives

`tests/test_session_countdown.py` defines a local `FakeClock` per
test or via a fixture. Not yet promoted to a shared `tests/conftest.py`
fixture — promote when a second module needs it.
