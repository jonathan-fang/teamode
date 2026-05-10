# Spike / Sketch Before Commit

## What This Is

A workflow pattern for running throwaway experiments before committing to an implementation approach. Use a spike when you're unsure if something is technically feasible. Use a sketch when you need to compare visual approaches.

This is not a skill or a phase. It's a pattern you invoke manually before APM planning when uncertainty is high.

## When to Spike

- "Can discord.py do X?" — capability question about the library
- "Will this approach hit a Discord rate limit?" — API feasibility
- "How does the voice extension behave when Y?" — API behavior question
- "Is this fast enough?" — performance question

**Skip when:** You already know the approach works. Most TeaMode tasks are in well-understood territory.

## When to Sketch

- Comparing 2-3 embed / button-row layouts before picking one
- Testing how a new component looks alongside existing surfaces
- Validating that text fits in Discord mobile's clipped embed width

## How to Spike

### 1. Write the hypothesis

Before writing any code, state what you're testing:

```
Given: [setup / precondition]
When:  [action you'll take]
Then:  [expected result if the approach works]
```

Example:
```
Given: discord.py editing a single message every 10s for 50 minutes
When:  The bot updates the timer display 300 times
Then:  No 429 (rate limit) responses; edit latency stays under 1s
```

### 2. Run in a worktree

Use a git worktree so the spike doesn't pollute your working branch:

```bash
git worktree add /tmp/teamode-spike-edit-cadence -b spike/edit-cadence
cd /tmp/teamode-spike-edit-cadence
source .venv/bin/activate
```

Or use Claude Code's `isolation: "worktree"` on an Agent call to do this automatically.

### 3. Write working code, not pseudocode

The spike must produce runnable code that answers the hypothesis. A spike that says "this should work" without running it is worthless.

Keep it minimal — just enough code to answer the question. No tests, no error handling, no polish.

### 4. Record the verdict

```
VALIDATED   — the approach works; proceed with implementation
INVALIDATED — the approach doesn't work; here's why: [reason]
PARTIAL     — works with caveats: [what caveats]
```

Include the evidence: output, error messages, screenshots, timing numbers.

### 5. Clean up

```bash
cd ~/WSL/github.com/jonathan-fang/teamode
git worktree remove /tmp/teamode-spike-edit-cadence
git branch -d spike/edit-cadence
```

The spike code is disposable. The verdict is what matters — carry it forward into the Planner brief.

## How to Sketch

### 1. Create a minimal test file

For embed/component sketches, create a standalone discord.py bot that
posts the variant(s) in question to a sketch channel:

```python
# sketch_embed.py — throwaway, do not commit
import discord, os

intents = discord.Intents.default()
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    channel = client.get_channel(int(os.environ["SKETCH_CHANNEL_ID"]))
    embed_a = discord.Embed(title="Variant A", color=0x7B9D6F)
    await channel.send(embed=embed_a)
    # ... variant B, etc.

client.run(os.environ["DISCORD_BOT_TOKEN"])
```

### 2. Compare variants

Run 2-3 variants side by side (or sequentially). Take screenshots or notes on each.

### 3. Pick one, discard the rest

The sketch file is disposable. The decision is what matters — record it in the UI Decisions subsection of the Implementation Plan.

## Feeding Results into APM

When initiating the Planner, include the spike/sketch verdict:

> "Spike result: discord.py message edits at 10s cadence for 50 minutes succeed without 429s. Backoff path tested via deliberate burst — safe to ship. See spike verdict for details."

This prevents the Planner from proposing an approach that was already invalidated.

## Example: Full Spike Cycle

```
1. Question: Can the bot reliably play reverie.wav in a voice channel
   after holding the connection idle for 50 minutes?

2. Hypothesis:
   Given: Bot joined voice channel, no audio sent for 50 minutes
   When:  voice_client.play(FFmpegPCMAudio("assets/reverie.wav")) is called
   Then:  Reverie plays through the channel within 1 second of zero

3. Spike (in worktree):
   - Wrote 30-line script that joined voice, slept 50 min, played reverie
   - Result: Voice connection survived; playback succeeded on 5/5 trials
   - One trial showed a brief reconnect during a wifi blip, but
     discord.py auto-reconnected and reverie still played

4. Verdict: VALIDATED with caveat
   - Reliable in normal network conditions
   - Auto-reconnect handles brief blips transparently
   - For production, add a fallback text mention if play raises

5. Planner brief: "Voice playback at zero is reliable; include a text
   mention fallback for the rare hard-failure case."
```
