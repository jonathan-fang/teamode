# discord.py Gotchas — TeaMode notes

Project-specific gotchas we hit while building TeaMode. Lives next to
the offline API reference snapshots so they show up in the same
search.

## Event registration via `Client.event(func)`

`Client.event(func)` uses **`func.__name__`** to determine which
Discord gateway event the handler responds to. There is no explicit
event-name parameter.

This means:

- `async def on_ready(self): ...` → registers as `on_ready` ✓
- `async def _on_ready(self): ...` → registers as `_on_ready` ✗ — no
  Discord event by that name, handler **never fires**, no error
  raised.

**The bug is silent.** The bot connects to the gateway successfully,
but the `on_ready` body never runs. You only notice when something
that *was* supposed to happen at ready (e.g. slash-command sync to a
dev guild) doesn't.

### TeaMode caught this in T2.2 smoke test

The worker followed Python convention and prefixed the method name
with `_` to mark it private. `client.event(self._on_ready)` registered
under the wrong name. `/teamode` never appeared in Discord even
though the bot connected cleanly. Fixed by renaming to `on_ready`
(commit `006694f`).

### Rule

Event handler methods on a bot class are part of discord.py's public
contract — name them by the event they handle (`on_ready`,
`on_message`, `on_voice_state_update`), not by Python visibility
convention.

If you need both a "private internal" and a "public registered" form,
register a thin wrapper:

```python
self.client.event(self.on_ready)  # discord.py reads __name__

async def on_ready(self) -> None:
    await self._real_on_ready_logic()
```
