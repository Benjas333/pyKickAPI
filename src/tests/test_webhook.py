# ruff: noqa: ANN201
from __future__ import annotations

import asyncio
import warnings
from typing import TYPE_CHECKING, Any, get_origin

import pytest
from pydantic import TypeAdapter, ValidationError

from betterKickAPI.eventsub.events import (
        ChannelFollowEvent,
        ChannelSubscriptionGiftsEvent,
        ChannelSubscriptionNewEvent,
        ChannelSubscriptionRenewalEvent,
        ChatMessageEvent,
        LivestreamMetadataUpdatedEvent,
        LivestreamStatusUpdatedEvent,
        ModerationBannedEvent,
)
from betterKickAPI.eventsub.webhook import KickWebhook

if TYPE_CHECKING:
        from betterKickAPI.kick import Kick

CHANNEL_QUERIES = ["ijenz", "imantado", "elglogloking"]
timeout = 30.0 # in seconds


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
        prefix = f"[{payload.broadcaster.channel_slug}]"
        print(f"{prefix} {payload.sender.channel_slug}: {payload.content}")


async def async_on_channel_follow(payload: ChannelFollowEvent):
        expect(payload, ChannelFollowEvent)
        await asyncio.sleep(5)  # example stuff
        prefix = f"[{payload.broadcaster.channel_slug}]"
        print(f"{prefix} {payload.follower.channel_slug} started following!")


def on_channel_subscription_renewal(payload: ChannelSubscriptionRenewalEvent):
        expect(payload, ChannelSubscriptionRenewalEvent)
        prefix = f"[{payload.broadcaster.channel_slug}]"
        print(f"{prefix} {payload.subscriber.channel_slug} subbed for {payload.duration} months!")
        assert payload.duration > 1


def on_channel_subscription_gifts(payload: ChannelSubscriptionGiftsEvent):
        expect(payload, ChannelSubscriptionGiftsEvent)
        assert len(payload.giftees)
        prefix = f"[{payload.broadcaster.channel_slug}]"
        print(f"{prefix} {payload.gifter.channel_slug} gifted {len(payload.giftees)} sub(s)!")
        for gift in payload.giftees:
                print(f"{prefix} {gift.channel_slug} got a gifted sub!")


def on_channel_subscription_new(payload: ChannelSubscriptionNewEvent):
        expect(payload, ChannelSubscriptionNewEvent)
        prefix = f"[{payload.broadcaster.channel_slug}]"
        print(f"{prefix} {payload.subscriber.channel_slug} has subscribed!")
        assert payload.duration < 2


def on_livestream_status_updated(payload: LivestreamStatusUpdatedEvent):
        expect(payload, LivestreamStatusUpdatedEvent)
        prefix = f"[{payload.broadcaster.channel_slug}]"
        text = "live" if payload.is_live else "offline"
        print(f"{prefix} Broadcaster is now {text}")
        assert (payload.ended_at is None) if payload.is_live else (payload.ended_at is not None)


def on_livestream_metadata_updated(payload: LivestreamMetadataUpdatedEvent):
        expect(payload, LivestreamMetadataUpdatedEvent)
        prefix = f"[{payload.broadcaster.channel_slug}]"
        print(f"{prefix} Changed metadata: {payload.metadata.model_dump_json(indent=2)}")
        assert payload.broadcaster.identity is None


def on_moderation_ban(payload: ModerationBannedEvent):
        expect(payload, ModerationBannedEvent)
        prefix = f"[{payload.broadcaster.channel_slug}]"
        print(
                f"{prefix} {payload.moderator.channel_slug} has banned {payload.banned_user.channel_slug}:\n"
                f"    {payload.metadata.reason}\n"
                f"    Until: {payload.metadata.expires_at}"
        )


@pytest.mark.asyncio
async def test_webhook(kick_api: Kick):
        global timeout
        webhook = KickWebhook(kick_api, force_app_auth=True)
        await webhook.unsubscribe_all()
        await webhook.start()

        for channel_slug in CHANNEL_QUERIES:
                channels = await kick_api.get_channels(slug=channel_slug)
                if not len(channels):
                        continue
                channel = channels[0]
                await webhook.listen_chat_message_sent(channel.broadcaster_user_id, sync_on_message)
                await webhook.listen_channel_follow(channel.broadcaster_user_id, async_on_channel_follow)
                await webhook.listen_channel_subscription_new(channel.broadcaster_user_id, on_channel_subscription_new)
                await webhook.listen_channel_subscription_renewal(
                        channel.broadcaster_user_id,
                        on_channel_subscription_renewal,
                )
                await webhook.listen_channel_subscription_gifts(channel.broadcaster_user_id, on_channel_subscription_gifts)
                await webhook.listen_livestream_status_updated(channel.broadcaster_user_id, on_livestream_status_updated)
                await webhook.listen_livestream_metadata_updated(channel.broadcaster_user_id, on_livestream_metadata_updated)
                await webhook.listen_moderation_banned(channel.broadcaster_user_id, on_moderation_ban)

        events = await kick_api.get_events_subscriptions(force_app_auth=True)
        assert len(events) != 0

        while timeout > 0:
                print(f"{timeout}s left")
                await asyncio.sleep(1.0)
                timeout -= 1

        await webhook.stop()
        events = await kick_api.get_events_subscriptions(force_app_auth=True)
        assert len(events) == 0
