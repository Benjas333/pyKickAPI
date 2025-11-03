# ruff: noqa: ANN201
from __future__ import annotations

import asyncio
import warnings
from logging import getLogger
from typing import TYPE_CHECKING, Any, get_origin

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
        from betterKickAPI.kick import Kick

FORCE_APP: bool = True
timeout: float = 60  # in seconds
logger = getLogger("kickAPI.tests.test_webhook")


def expect(data: Any, expected_type: Any):  # noqa: ANN401
        origin = get_origin(expected_type)
        is_list_type = (expected_type is list) or (origin is list)

        if is_list_type and isinstance(data, list) and len(data) == 0:
                warnings.warn("Empty array. Possible false-positive.", pytest.PytestWarning, stacklevel=2)
        try:
                TypeAdapter(expected_type).validate_python(data)
        except ValidationError as e:
                pytest.fail(f"ValidationError: {e}")


def sync_on_message(payload: ChatMessageEvent):
        expect(payload, ChatMessageEvent)
        logger.info("[%s] %s: %s", payload.broadcaster.channel_slug, payload.sender.channel_slug, payload.content)


async def async_on_channel_follow(payload: ChannelFollowEvent):
        expect(payload, ChannelFollowEvent)
        await asyncio.sleep(1)  # example stuff
        logger.info("[%s] %s started following!", payload.broadcaster.channel_slug, payload.follower.channel_slug)


def on_channel_subscription_renewal(payload: ChannelSubscriptionRenewalEvent):
        expect(payload, ChannelSubscriptionRenewalEvent)
        logger.info(
                "[%s] %s subbed for %d months!",
                payload.broadcaster.channel_slug,
                payload.subscriber.channel_slug,
                payload.duration,
        )
        assert payload.duration > 1


def on_channel_subscription_gifts(payload: ChannelSubscriptionGiftsEvent):
        expect(payload, ChannelSubscriptionGiftsEvent)
        length = len(payload.giftees)
        assert length
        logger.info("[%s] %s gifted %d sub(s)!", payload.broadcaster.channel_slug, payload.gifter.channel_slug, length)
        for gift in payload.giftees:
                logger.info("[%s] %s got a gifted sub!", payload.broadcaster.channel_slug, gift.channel_slug)


def on_channel_subscription_new(payload: ChannelSubscriptionNewEvent):
        expect(payload, ChannelSubscriptionNewEvent)
        logger.info("[%s] %s has subscribed!", payload.broadcaster.channel_slug, payload.subscriber.channel_slug)
        assert payload.duration < 2


def on_livestream_status_updated(payload: LivestreamStatusUpdatedEvent):
        expect(payload, LivestreamStatusUpdatedEvent)
        text = "live" if payload.is_live else "offline"
        logger.info("[%s] Broadcaster is now %s", payload.broadcaster.channel_slug, text)
        assert (payload.ended_at is None) if payload.is_live else (payload.ended_at is not None)


def on_livestream_metadata_updated(payload: LivestreamMetadataUpdatedEvent):
        expect(payload, LivestreamMetadataUpdatedEvent)
        logger.info(
                "[%s] Changed metadata: %s",
                payload.broadcaster.channel_slug,
                payload.metadata.model_dump_json(indent=2),
        )
        assert payload.broadcaster.identity is None


def on_moderation_ban(payload: ModerationBannedEvent):
        expect(payload, ModerationBannedEvent)
        logger.info(
                "[%s] %s has banned %s:\n    %s\n    Until: %s",
                payload.broadcaster.channel_slug,
                payload.moderator.channel_slug,
                payload.banned_user.channel_slug,
                payload.metadata.reason,
                payload.metadata.expires_at,
        )


def on_kicks_gifted(payload: KicksGiftedEvent):
        expect(payload, KicksGiftedEvent)
        logger.info(
                "[%s] %s has gifted %d kicks (%s-%s): %s\nFull send/name:%s",
                payload.broadcaster.channel_slug,
                payload.sender.channel_slug,
                payload.gift.amount,
                payload.gift.type,
                payload.gift.tier,
                payload.gift.message,
                payload.gift.name,
        )


@pytest.mark.asyncio
async def test_webhook(kick_api: Kick):
        global timeout

        webhook = KickWebhook(kick_api, force_app_auth=True if kick_api.user_auth_token is not None else FORCE_APP)
        await webhook.unsubscribe_all()
        if kick_api.user_auth_token:
                webhook.force_app_auth = False
                await webhook.unsubscribe_all()
                webhook.force_app_auth = FORCE_APP
        try:
                webhook.start()

                waiting = 10
                logger.info("Waiting %ds for webhook url setting...", waiting)
                while waiting > 0:
                        logger.info("%ds left", waiting)
                        await asyncio.sleep(1.0)
                        waiting -= 1

                livestreams = [
                        (live.broadcaster_user_id, live.slug)
                        for live in await kick_api.get_livestreams(limit=3, sort="viewer_count")
                ]
                sub_ids = []

                for user_id, slug in livestreams:
                        logger.info("Subscribing to: %s", slug)
                        sub_ids.append(await webhook.listen_chat_message_sent(user_id, sync_on_message))
                        sub_ids.append(await webhook.listen_channel_follow(user_id, async_on_channel_follow))
                        sub_ids.append(await webhook.listen_channel_subscription_new(user_id, on_channel_subscription_new))
                        sub_ids.append(
                                await webhook.listen_channel_subscription_renewal(user_id, on_channel_subscription_renewal)
                        )
                        sub_ids.append(
                                await webhook.listen_channel_subscription_gifts(user_id, on_channel_subscription_gifts)
                        )
                        sub_ids.append(await webhook.listen_livestream_status_updated(user_id, on_livestream_status_updated))
                        sub_ids.append(
                                await webhook.listen_livestream_metadata_updated(user_id, on_livestream_metadata_updated)
                        )
                        sub_ids.append(await webhook.listen_moderation_banned(user_id, on_moderation_ban))
                        sub_ids.append(await webhook.listen_kicks_gifted(user_id, on_kicks_gifted))

                events = await kick_api.get_events_subscriptions(force_app_auth=FORCE_APP)
                events_users_ids = {event.broadcaster_user_id for event in events}
                expected_user_ids = {user_id for (user_id, _) in livestreams}

                missing_ids = expected_user_ids.difference(events_users_ids)
                if len(missing_ids):
                        pytest.fail(f"There's missing user IDs in the actual subscribed events: {missing_ids}")

                extra_ids = events_users_ids.difference(expected_user_ids)
                if len(extra_ids):
                        pytest.fail(f"There's extra user IDs in the actual subscribed events: {extra_ids}")

                if len(events) != len(sub_ids):
                        warnings.warn(
                                "The actual amount of subscribed events differs from the requested ones",
                                pytest.PytestWarning,
                                stacklevel=1,
                        )

                while timeout > 0:
                        if timeout < 11:
                                logger.info("%ds left", timeout)
                        await asyncio.sleep(1.0)
                        timeout -= 1
        except KeyboardInterrupt:
                pass
        finally:
                await webhook.stop()
                logger.info("Webhook stopped")
        events = await kick_api.get_events_subscriptions(force_app_auth=FORCE_APP)
        assert len(events) == 0
