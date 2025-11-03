# ruff: noqa: ANN201, ANN202
from __future__ import annotations

import asyncio
import logging
import warnings
from typing import TYPE_CHECKING, Any, Callable, get_origin

import pytest
from pydantic import TypeAdapter, ValidationError

from betterKickAPI.eventsub.events import (
        ChannelFollowEvent,
        ChannelSubscriptionGiftsEvent,
        ChannelSubscriptionNewEvent,
        ChannelSubscriptionRenewalEvent,
        ChatMessageEvent,
        KicksGiftedEvent,
        LivestreamMetadataUpdatedEvent,
        LivestreamStatusUpdatedEvent,
        ModerationBannedEvent,
)
from betterKickAPI.eventsub.webhook import KickWebhook

if TYPE_CHECKING:
        from types import CoroutineType

        from betterKickAPI.eventsub.base import _E, EventCallback
        from betterKickAPI.kick import Kick

MAX_STREAMERS = 50
MAX_EVENTS = 3
logger = logging.getLogger("kickAPI.tests.test_webhook")


def expect(data: Any, expected_type: Any):  # noqa: ANN401
        origin = get_origin(expected_type)
        is_list_type = (expected_type is list) or (origin is list)

        if is_list_type and isinstance(data, list) and len(data) == 0:
                warnings.warn("Empty array. Possible false-positive.", pytest.PytestWarning, stacklevel=2)
        try:
                TypeAdapter(expected_type).validate_python(data)
        except ValidationError as e:
                pytest.fail(f"ValidationError: {e}")


class EventCounter:
        def __init__(
                self,
                webhook: KickWebhook,
                # livestreams: list[tuple[int, str]],
                max_streamers: int = 50,
                max_events: int = 5,
                tasks: set[asyncio.Task] | None = None,
        ) -> None:
                self.webhook = webhook
                # self.livestreams = livestreams
                self.max_streamers = max_streamers
                self._value = 0
                self._value_lock = asyncio.Lock()
                self.max_events = max_events
                self.tasks: set[asyncio.Task] = tasks or set()
                self.tasks_lock = asyncio.Lock()
                self.is_subscribing = False

        async def increment(self) -> int:
                async with self._value_lock:
                        self._value += 1
                        return self._value

        async def is_done(self, multiplier: int) -> bool:
                async with self._value_lock:
                        return self._value >= self.max_events * multiplier

        async def try_trigger_next(
                self,
                multiplier: int,
                listen_callback: Callable[[int, EventCallback[_E]], CoroutineType[Any, Any, str]],
                callback: Callable[[_E], CoroutineType[Any, Any, None]],
        ):
                new_value = await self.increment()
                if new_value != self.max_events * multiplier:
                        return
                async with self.tasks_lock:
                        if len(self.tasks):
                                self.is_subscribing = False
                                for task in self.tasks:
                                        task.cancel()
                                # await asyncio.gather(*self.tasks)
                await self.webhook.unsubscribe_all_local_knowns()
                await self.subscribe(listen_callback, callback)

        async def subscriber_worker(
                self,
                listen_callback: Callable[[int, EventCallback[_E]], CoroutineType[Any, Any, str]],
                callback: Callable[[_E], CoroutineType[Any, Any, None]],
        ):
                # tasks: set[asyncio.Task] = set()
                livestreams = [
                        live.broadcaster_user_id
                        for live in await self.webhook._kick.get_livestreams(limit=50, sort="viewer_count")  # noqa: SLF001
                ]
                for user_id in livestreams:
                        if not self.is_subscribing:
                                break
                        # logger.info("Subscribing to: %s", slug)
                        await listen_callback(user_id, callback)
                        # task = asyncio.create_task(listen_callback(user_id, callback))
                        # tasks.add(task)
                        # task.add_done_callback(tasks.discard)
                # await asyncio.gather(*tasks)

        async def subscribe(
                self,
                listen_callback: Callable[[int, EventCallback[_E]], CoroutineType[Any, Any, str]],
                callback: Callable[[_E], CoroutineType[Any, Any, None]],
        ):
                self.is_subscribing = True
                async with self.tasks_lock:
                        task = asyncio.create_task(self.subscriber_worker(listen_callback, callback))
                        self.tasks.add(task)
                        task.add_done_callback(self.tasks.discard)


@pytest.mark.asyncio
async def test_webhook_events(kick_api: Kick):  # noqa: C901
        webhook = KickWebhook(kick_api, force_app_auth=True)
        await webhook.unsubscribe_all()
        webhook.unsubscribe_on_handler_not_found = False

        # tasks: set[asyncio.Task] = set()
        # livestreams = [
        #         (live.broadcaster_user_id, live.slug)
        #         for live in await kick_api.get_livestreams(limit=50, sort="viewer_count")
        # ]
        counter = EventCounter(webhook, MAX_STREAMERS, MAX_EVENTS)
        end_event = asyncio.Event()

        async def on_message(payload: ChatMessageEvent):
                if await counter.is_done(1):
                        return
                await counter.try_trigger_next(1, webhook.listen_channel_follow, on_channel_follow)
                expect(payload, ChatMessageEvent)
                logger.info(
                        "====> [%s] %s: %s",
                        payload.broadcaster.channel_slug,
                        payload.sender.channel_slug,
                        payload.content,
                )

        async def on_channel_follow(payload: ChannelFollowEvent):
                if await counter.is_done(2):
                        return
                await counter.try_trigger_next(
                        2,
                        webhook.listen_channel_subscription_renewal,
                        on_channel_subscription_renewal,
                )
                expect(payload, ChannelFollowEvent)
                logger.info(
                        "====> [%s] %s started following!",
                        payload.broadcaster.channel_slug,
                        payload.follower.channel_slug,
                )

        async def on_channel_subscription_renewal(payload: ChannelSubscriptionRenewalEvent):
                if await counter.is_done(3):
                        return
                await counter.try_trigger_next(3, webhook.listen_channel_subscription_gifts, on_channel_subscription_gifts)
                expect(payload, ChannelSubscriptionRenewalEvent)
                logger.info(
                        "====> [%s] %s subbed for %d months!",
                        payload.broadcaster.channel_slug,
                        payload.subscriber.channel_slug,
                        payload.duration,
                )
                assert payload.duration > 1

        async def on_channel_subscription_gifts(payload: ChannelSubscriptionGiftsEvent):
                if await counter.is_done(4):
                        return
                await counter.try_trigger_next(4, webhook.listen_channel_subscription_new, on_channel_subscription_new)
                expect(payload, ChannelSubscriptionGiftsEvent)
                length = len(payload.giftees)
                assert length
                logger.info(
                        "====> [%s] %s gifted %d sub(s)!",
                        payload.broadcaster.channel_slug,
                        payload.gifter.channel_slug,
                        length,
                )
                for gift in payload.giftees:
                        logger.info("====> [%s] %s got a gifted sub!", payload.broadcaster.channel_slug, gift.channel_slug)

        async def on_channel_subscription_new(payload: ChannelSubscriptionNewEvent):
                if await counter.is_done(5):
                        return
                await counter.try_trigger_next(5, webhook.listen_livestream_status_updated, on_livestream_status_updated)
                expect(payload, ChannelSubscriptionNewEvent)
                logger.info(
                        "====> [%s] %s has subscribed!", payload.broadcaster.channel_slug, payload.subscriber.channel_slug
                )
                assert payload.duration < 2

        async def on_livestream_status_updated(payload: LivestreamStatusUpdatedEvent):
                if await counter.is_done(6):
                        return
                await counter.try_trigger_next(6, webhook.listen_livestream_metadata_updated, on_livestream_metadata_updated)
                expect(payload, LivestreamStatusUpdatedEvent)
                text = "live" if payload.is_live else "offline"
                logger.info("====> [%s] Broadcaster is now %s", payload.broadcaster.channel_slug, text)
                assert (payload.ended_at is None) if payload.is_live else (payload.ended_at is not None)

        async def on_livestream_metadata_updated(payload: LivestreamMetadataUpdatedEvent):
                if await counter.is_done(7):
                        return
                await counter.try_trigger_next(7, webhook.listen_moderation_banned, on_moderation_ban)
                expect(payload, LivestreamMetadataUpdatedEvent)
                logger.info(
                        "====> [%s] Changed metadata: %s",
                        payload.broadcaster.channel_slug,
                        payload.metadata.model_dump_json(indent=2),
                )
                assert payload.broadcaster.identity is None

        async def on_moderation_ban(payload: ModerationBannedEvent):
                if await counter.is_done(8):
                        return
                await counter.try_trigger_next(8, webhook.listen_kicks_gifted, on_kicks_gifted)
                expect(payload, ModerationBannedEvent)
                logger.info(
                        "====> [%s] %s has banned %s:\n    %s\n    Until: %s",
                        payload.broadcaster.channel_slug,
                        payload.moderator.channel_slug,
                        payload.banned_user.channel_slug,
                        payload.metadata.reason,
                        payload.metadata.expires_at,
                )

        async def on_kicks_gifted(payload: KicksGiftedEvent):
                if await counter.is_done(9):
                        return
                new_value = await counter.increment()
                if new_value == counter.max_events * 9:
                        await webhook.unsubscribe_all_local_knowns()
                        end_event.set()
                expect(payload, KicksGiftedEvent)
                logger.info(
                        "====> [%s] %s has gifted %d kicks (%s-%s): %s \nFull send/name:%s",
                        payload.broadcaster.channel_slug,
                        payload.sender.channel_slug,
                        payload.gift.amount,
                        payload.gift.type,
                        payload.gift.tier,
                        payload.gift.message,
                        payload.gift.name,
                )

        try:
                webhook.start()

                waiting = 10
                logger.info("Waiting %ds for webhook url setting...", waiting)
                while waiting > 0:
                        logger.info("%ds left", waiting)
                        await asyncio.sleep(1.0)
                        waiting -= 1

                await counter.subscribe(webhook.listen_chat_message_sent, on_message)

                await end_event.wait()

                waiting = 10
                while waiting > 0:
                        if waiting < 11:
                                logger.info("%ds left", waiting)
                        await asyncio.sleep(1.0)
                        waiting -= 1
        except KeyboardInterrupt:
                pass
        finally:
                # await asyncio.gather(*tasks)
                await webhook.stop()
                logger.info("Webhook stopped")
        events = await kick_api.get_events_subscriptions(force_app_auth=True)
        assert len(events) == 0
