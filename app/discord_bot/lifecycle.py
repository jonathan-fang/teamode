"""End-of-session sequence, follow-up reactions, and solo-grace/handoff voice events."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import cast

import discord

from app import voice
from app.constants import (
    AUTO_HANDOFF_ANNOUNCE,
    END_EMBED_BODY,
    END_EMBED_TITLE,
    END_OF_SESSION_MENTION,
    END_OF_SESSION_NO_MENTION,
    FOLLOWUP_PROMPT,
    FOLLOWUP_TIMEOUT_SECONDS,
    FOLLOWUP_WHY_PROMPT,
    REFLECT_EMBED_DESCRIPTION,
    REFLECT_EMBED_TITLE,
    SOLO_GRACE_ENDED,
    SOLO_GRACE_SECONDS,
)
from app.discord_bot.views import COLORS, _EditState
from app.session import SessionRegistry

logger = logging.getLogger(__name__)


class LifecycleMixin:
    """End-of-session sequence, follow-up reactions, and voice-state handling.

    Mixed into :class:`TeaModeBot`.
    """

    # Attributes provided by TeaModeBot.__init__ — declared here so pyright
    # can type-check the mixin's own methods in isolation.
    client: discord.Client
    _registry: SessionRegistry
    _reflect_message_ids: dict[int, int]
    _watchdog_tasks: dict[int, asyncio.Task[None]]
    _solo_grace_tasks: dict[int, asyncio.Task[None]]
    _countdown_tasks: dict[int, asyncio.Task[None]]
    _voice_clients: dict[int, discord.VoiceClient]
    _edit_states: dict[int, _EditState]

    async def _run_end_of_session(
        self,
        *,
        session_id: int,
        voice_client: discord.VoiceClient,
        channel: discord.abc.Messageable | None,
    ) -> None:
        """Run the full end-of-session sequence after countdown reaches zero.

        Order: Session-complete embed (@-mention) → reverie+disconnect
        → Reflect embed (facilitator prompt) → pre-populate reactions
        → 3-minute watchdog.
        """
        if channel is None:
            logger.warning(
                "No channel reference for session %s end-of-session sequence",
                session_id,
            )
            return

        # Step a: Snapshot voice channel members (excluding the bot).
        voice_channel = voice_client.channel
        if isinstance(voice_channel, discord.VoiceChannel):
            members = [
                m
                for m in voice_channel.members
                if not m.bot
                and m.id != (self.client.user.id if self.client.user else None)
            ]
        else:
            members = []

        if members:
            mentions = " ".join(m.mention for m in members)
            mention_content = END_OF_SESSION_MENTION.format(mentions=mentions)
        else:
            mention_content = END_OF_SESSION_NO_MENTION

        # Step b: Post Session-complete embed with the @-mention content.
        session_complete_embed = discord.Embed(
            title=END_EMBED_TITLE,
            description=f"### {END_EMBED_BODY}",
            color=COLORS["end_of_session"],
        )
        await channel.send(content=mention_content, embed=session_complete_embed)

        # Step c: Reverie playback + disconnect.
        playback_ok = await voice.play_reverie_then_disconnect(voice_client)
        if not playback_ok:
            logger.warning("Reverie playback failed for session %s", session_id)

        # Step d: Post Reflect message with facilitator prompt.
        facilitator_prompt = FOLLOWUP_PROMPT
        reflect_embed = discord.Embed(
            title=REFLECT_EMBED_TITLE,
            description=REFLECT_EMBED_DESCRIPTION,
            color=COLORS["end_of_session"],
        )
        reflect_msg = await channel.send(
            content=facilitator_prompt, embed=reflect_embed
        )

        # Step e: Pre-populate reactions on the Reflect message.
        await reflect_msg.add_reaction("✅")
        await reflect_msg.add_reaction("⛔")

        # Step f: Store the Reflect message id for the reaction listener.
        self._reflect_message_ids[session_id] = reflect_msg.id

        # Step g: 3-minute watchdog.
        async def _watchdog() -> None:
            try:
                await asyncio.sleep(FOLLOWUP_TIMEOUT_SECONDS)
            except asyncio.CancelledError:
                return
            # Watchdog fired — mark timeout and clean up.
            try:
                self._registry.mark_followup_timeout(session_id=session_id)
            except Exception:
                logger.exception(
                    "mark_followup_timeout failed for session %s", session_id
                )
            self._reflect_message_ids.pop(session_id, None)
            logger.info(
                "Follow-up watchdog fired for session %s — marked followup_timeout",
                session_id,
            )

        task: asyncio.Task[None] = asyncio.create_task(_watchdog())
        self._watchdog_tasks[session_id] = task

    async def on_raw_reaction_add(
        self, payload: discord.RawReactionActionEvent
    ) -> None:
        """Facilitator-authoritative reaction handler for the Reflect message.

        The facilitator's ✅ or ⛔ reaction on the Reflect embed sets
        ``completed_intention`` and terminates the watchdog. Non-facilitator
        reactions and the bot's own pre-populated reactions are ignored.
        """
        # Ignore the bot's own pre-populated reactions.
        if self.client.user is not None and payload.user_id == self.client.user.id:
            return

        # Find the session whose Reflect message matches this payload.
        session_id: int | None = None
        for sid, msg_id in self._reflect_message_ids.items():
            if msg_id == payload.message_id:
                session_id = sid
                break
        if session_id is None:
            return

        # Look up the session; it must be in followup state.
        session = self._registry.get(session_id)
        if session is None:
            return
        from app.session import SessionState

        if session.state != SessionState.FOLLOWUP:
            return

        emoji_str = str(payload.emoji)
        if emoji_str not in ("✅", "⛔"):
            return

        # Non-facilitator reaction: log only.
        if payload.user_id != int(session.facilitator_id):
            logger.info(
                "Non-facilitator reaction %s by user %s on session %s — logged only",
                emoji_str,
                payload.user_id,
                session_id,
            )
            return

        # Facilitator reaction — authoritative answer.
        task = self._watchdog_tasks.pop(session_id, None)
        if task is not None:
            task.cancel()

        # Pop the Reflect-message id to prevent duplicate handling.
        self._reflect_message_ids.pop(session_id, None)

        if emoji_str == "✅":
            self._registry.mark_completed(
                session_id=session_id,
                completed_intention=1,
                followup_note=None,
            )
        else:
            # ⛔ — record incomplete, then post the "why" prompt.
            self._registry.mark_completed(
                session_id=session_id,
                completed_intention=0,
                followup_note=None,
            )
            channel = self.client.get_channel(int(session.text_channel_id))
            if channel is not None:
                await cast(discord.abc.Messageable, channel).send(
                    FOLLOWUP_WHY_PROMPT.format(facilitator_id=session.facilitator_id)
                )

    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        """Automatic facilitator handoff and solo-grace watchdog for voice events.

        Fires whenever any guild member's voice state changes.

        Join path: if the facilitator rejoins a channel with an active
        session and a solo-grace watchdog is pending, cancel the watchdog.

        Leave path: if the facilitator leaves a channel with an active session
        and no other humans remain, arm the 5-minute solo-grace watchdog. If
        other humans remain, pick a new facilitator at random (auto-handoff).
        """
        # Detect a join into a voice channel: after.channel is set and either
        # the member was not in voice before, or they moved to a different channel.
        if after.channel is not None and (
            before.channel is None or before.channel.id != after.channel.id
        ):
            joined_session = self._registry.find_active_in_voice_channel(
                str(after.channel.id)
            )
            if (
                joined_session is not None
                and str(member.id) == joined_session.facilitator_id
                and joined_session.session_id in self._solo_grace_tasks
            ):
                # Facilitator rejoined within the grace window — cancel watchdog.
                task = self._solo_grace_tasks.pop(joined_session.session_id)
                task.cancel()
                # No need to await — the watchdog's CancelledError handler cleans up.

        # Step 1 — Did this member just leave a voice channel?
        if before.channel is None:
            return
        if after.channel is not None and after.channel.id == before.channel.id:
            return  # Same channel — not a leave event.

        # Step 2 — Is there an in-progress session in the channel they left?
        session = self._registry.find_active_in_voice_channel(str(before.channel.id))
        if session is None:
            return

        # Step 3 — Is the leaver the current facilitator?
        if str(member.id) != session.facilitator_id:
            return

        # Step 4 — Count remaining human members (exclude the leaver and the bot).
        bot_id = self.client.user.id if self.client.user else None
        remaining = [
            m
            for m in before.channel.members
            if not m.bot and m.id != member.id and m.id != bot_id
        ]

        if not remaining:
            # Solo leave — arm the 5-minute rejoin watchdog.
            # Defensive guard: if one is already pending, don't double-arm.
            if session.session_id not in self._solo_grace_tasks:
                task = asyncio.create_task(
                    self._run_solo_grace(session_id=session.session_id),
                    name=f"solo-grace:{session.session_id}",
                )
                self._solo_grace_tasks[session.session_id] = task
            return

        # Step 5 — Pick a new facilitator at random and record the handoff.
        new_facilitator = random.choice(remaining)
        old_facilitator_id = (
            session.facilitator_id
        )  # snapshot before mark_handoff updates it
        self._registry.mark_handoff(
            session_id=session.session_id,
            handoff_facilitator_id=str(new_facilitator.id),
        )

        # Step 6 — Announce in the text channel.
        channel = self.client.get_channel(int(session.text_channel_id))
        if channel is not None:
            content = AUTO_HANDOFF_ANNOUNCE.format(
                old_facilitator_id=old_facilitator_id,
                new_facilitator_id=new_facilitator.id,
            )
            try:
                await channel.send(content)  # type: ignore[union-attr]
            except discord.HTTPException:
                logger.exception(
                    "Failed to announce auto handoff for session %s",
                    session.session_id,
                )

    async def _run_solo_grace(
        self,
        *,
        session_id: int,
        sleep_seconds: float = SOLO_GRACE_SECONDS,
    ) -> None:
        """5-minute rejoin watchdog for solo facilitator-leave.

        Sleeps ``sleep_seconds``. If cancelled (facilitator rejoined), exits
        cleanly. If the sleep completes, terminates the session as
        ``cancelled``: rewrites the timer message, cancels the countdown task,
        disconnects voice, and writes status='cancelled' to SQLite.

        ``sleep_seconds`` defaults to ``SOLO_GRACE_SECONDS``. Tests pass a
        small value (e.g. 0 or 0.01) to exercise the timeout path without
        waiting 5 minutes.
        """
        try:
            await asyncio.sleep(sleep_seconds)
        except asyncio.CancelledError:
            # Facilitator rejoined within the grace window — nothing to do.
            return

        # Timeout fired. Resolve resources defensively (pops are no-ops if missing).
        countdown_task = self._countdown_tasks.pop(session_id, None)
        voice_client = self._voice_clients.pop(session_id, None)
        edit_state = self._edit_states.pop(session_id, None)
        self._solo_grace_tasks.pop(session_id, None)

        # 1) Cancel the countdown task so it doesn't trigger end-of-session.
        if countdown_task is not None:
            countdown_task.cancel()
            try:
                await countdown_task
            except (asyncio.CancelledError, Exception):
                # Best-effort: a swallowed exception here is acceptable —
                # we're tearing the session down anyway.
                pass

        # 2) Rewrite the timer message.
        if edit_state is not None:
            try:
                await edit_state.message.edit(content=SOLO_GRACE_ENDED)
            except discord.HTTPException:
                logger.exception(
                    "Failed to edit timer message on solo-grace timeout for session %s",
                    session_id,
                )

        # 3) Disconnect voice (no reverie).
        if voice_client is not None:
            try:
                await voice.disconnect(voice_client)
            except Exception:
                logger.exception(
                    "Failed to disconnect voice on solo-grace timeout for session %s",
                    session_id,
                )

        # 4) Write status='cancelled' to SQLite.
        try:
            self._registry.mark_cancelled(session_id=session_id)
        except Exception:
            logger.exception(
                "Failed to mark session %s cancelled on solo-grace timeout",
                session_id,
            )
