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

## `on_interaction` does not need to forward slash commands

discord.py routes interactions in two layers:

1. The gateway delivers `INTERACTION_CREATE`.
2. *Before* dispatching to user code's `on_interaction`, discord.py's
   internal `parse_interaction_create` checks the type. If it is
   `APPLICATION_COMMAND`, the interaction is routed through
   `_state._command_tree` — the tree finds the matching slash-command
   callback and runs it. If it is `COMPONENT` (button click) or
   `MODAL_SUBMIT`, the tree ignores it.
3. *Then* `on_interaction` fires, regardless of whether the tree
   handled it.

So a custom `on_interaction` listener that wants to handle component
clicks **must not** try to re-dispatch application commands to the
tree. There is no `CommandTree.process_application_commands(...)`
method to call (that name does not exist in discord.py 2.x), and even
if there were, the tree has already handled the interaction by the
time `on_interaction` fires.

The correct shape is to filter on type and ignore everything but
components / modal submits:

```python
async def on_interaction(self, interaction: discord.Interaction) -> None:
    if interaction.type != discord.InteractionType.component:
        return
    # ... custom_id parsing and dispatch
```

## `discord.ui.Label.component` reads as `Item[Unknown]` to pyright

When a `discord.ui.Modal` wraps a `TextInput` inside a `Label`,
accessing the input's `.value` via `label.component.value` triggers a
pyright error because `Label.component` is annotated as
`Item[Unknown]` rather than the concrete `TextInput` type.

Workaround: `cast` at the read site.

```python
from typing import cast

text = cast(
    discord.ui.TextInput[discord.ui.Modal],
    self.intention_field.component,
).value
```

This is a discord.py 2.x type-erasure quirk, not a bug in our code.
Use the same cast in tests that introspect the modal's components.
