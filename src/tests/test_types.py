# ruff: noqa: ANN201, BLE001
# import asyncio
from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any, get_origin

import pytest
from pydantic import TypeAdapter, ValidationError

from betterKickAPI.helper import first
from betterKickAPI.object.api import (
        Category,
        Channel,
        DeleteModerationBanResponse,
        EventSubscription,
        KicksLeaderboard,
        LiveStream,
        LiveStreamStats,
        PostChatMessageResponse,
        PostEventSubscriptionResponse,
        PostModerationBanResponse,
        TokenIntrospection,
        User,
)
from betterKickAPI.types import EventSubEvents

if TYPE_CHECKING:
        from collections.abc import Generator

        from betterKickAPI.kick import Kick


# -------------------

CHANNEL_QUERIES = ["Benjas333", "conterstine", "natalan"]
CATEGORY_QUERIES = ["Minecraft", "IRL", "a"]


@pytest.fixture(scope="session")
def errors() -> Generator[list[Exception], Any, None]:
        errs: list[Exception] = []
        yield errs
        if errs:
                print("\n--- Schema validation errors collected during test run ---")
                for i, e in enumerate(errs, 1):
                        print(f"\n[{i}] {type(e).__name__}")
                        print(e)
                pytest.fail(f"{len(errs)} schema validation error(s) found")


# -------------------
# Helpers
# -------------------
# def _dump_json(obj: Any) -> bytes:
#         def default(o: Any) -> str | dict[str, Any] | Any:
#                 if hasattr(o, "model_dump"):
#                         return o.model_dump()
#                 if hasattr(o, "__dict__"):
#                         return o.__dict__
#                 return str(o)

#         return orjson.dumps(obj, default=default)


def expect(data: Any, expected_type: Any, errors_list: list[Exception]):  # noqa: ANN401
        origin = get_origin(expected_type)
        is_list_type = (expected_type is list) or (origin is list)

        if is_list_type and isinstance(data, list) and len(data) == 0:
                warnings.warn("Empty array. Possible false-positive.", pytest.PytestWarning, stacklevel=2)
        try:
                TypeAdapter(expected_type).validate_python(data)
        except ValidationError as e:
                errors_list.append(e)
        #         return
        # dumped = _dump_json(parsed).decode()
        # if not search(r'"\w+"\s*:\s*""', dumped):
        #         return
        # errors_list.append(AssertionError(f"Empty-string fields found for {expected_type!r}: {dumped[:500]}"))


# -------------------
# Tests
# -------------------
@pytest.mark.parametrize("query", CATEGORY_QUERIES)
@pytest.mark.asyncio
async def test_categories(kick_api: Kick, errors: list[Exception], query: str):
        categories = kick_api.get_categories(query)
        # expect(categories, AsyncGenerator[Category, None], errors)
        try:
                async for category in categories:
                        expect(category, Category, errors)
        except Exception as e:
                errors.append(e)


@pytest.mark.parametrize("query", CATEGORY_QUERIES)
@pytest.mark.asyncio
async def test_category(kick_api: Kick, errors: list[Exception], query: str):
        first_category = await first(kick_api.get_categories(query))
        expect(first_category, Category | None, errors)
        if not first_category:
                pytest.skip(f"No category returned for query: {query}")

        category = await kick_api.get_category(first_category.id)
        expect(category, Category, errors)


@pytest.mark.asyncio
async def test_token_introspect(kick_api: Kick, errors: list[Exception]):
        token_introspection = await kick_api.token_introspect(kick_api.used_token)  # type: ignore
        expect(token_introspection, TokenIntrospection, errors)


@pytest.mark.asyncio
async def test_actual_user(kick_api: Kick, errors: list[Exception]):
        users = await kick_api.get_users()

        expect(users, list[User], errors)


@pytest.mark.parametrize("query", CHANNEL_QUERIES)
@pytest.mark.asyncio
async def test_users(kick_api: Kick, errors: list[Exception], query: str):
        channel = await kick_api.get_channels(slug=query)
        if not len(channel):
                pytest.skip(f"No user returned for query: {query}")

        users = await kick_api.get_users(channel[0].broadcaster_user_id)
        expect(users[0], User, errors)


@pytest.mark.asyncio
async def test_actual_channel(kick_api: Kick, errors: list[Exception]):
        channels = await kick_api.get_channels()

        expect(channels, list[Channel], errors)


@pytest.mark.parametrize("query", CHANNEL_QUERIES)
@pytest.mark.asyncio
async def test_channels(kick_api: Kick, errors: list[Exception], query: str):
        channels = await kick_api.get_channels(slug=query)
        expect(channels, list[Channel], errors)


@pytest.mark.parametrize("query", CATEGORY_QUERIES)
@pytest.mark.asyncio
async def test_patch_channels(kick_api: Kick, errors: list[Exception], query: str):
        category = await first(kick_api.get_categories(query))
        if not category:
                pytest.skip(f"No category returned for query: {query}")

        ok = await kick_api.patch_channel(category.id, stream_title="kickAPI.tests.test_patch_channels")
        expect(ok, bool, errors)


@pytest.mark.asyncio
async def test_bot_chat_message(kick_api: Kick, errors: list[Exception]):
        message_data = await kick_api.post_chat_message("kickAPI.tests.test_bot_chat_message")
        expect(message_data, PostChatMessageResponse, errors)


@pytest.mark.asyncio
async def test_user_chat_message(kick_api: Kick, errors: list[Exception]):
        broadcaster = await kick_api.get_channels()
        if not len(broadcaster):
                pytest.skip("No actual broadcaster returned.")

        message_data = await kick_api.post_chat_message(
                "kickAPI.tests.test_user_chat_message",
                "user",
                broadcaster[0].broadcaster_user_id,
        )
        expect(message_data, PostChatMessageResponse, errors)


@pytest.mark.parametrize("query", CHANNEL_QUERIES)
@pytest.mark.asyncio
async def test_moderation_ban(kick_api: Kick, errors: list[Exception], query: str):
        channels = await kick_api.get_channels(slug=query)
        if not len(channels):
                pytest.skip(f"No channel returned for query: {query}")

        broadcaster = await kick_api.get_channels()
        if not len(broadcaster):
                pytest.skip("No actual broadcaster returned.")

        ban_data = await kick_api.post_moderation_ban(
                channels[0].user_id,
                broadcaster[0].broadcaster_user_id,
                5,
                "kickAPI.tests.test_moderation_ban",
        )
        expect(ban_data, PostModerationBanResponse, errors)


@pytest.mark.parametrize("query", CHANNEL_QUERIES)
@pytest.mark.asyncio
async def test_delete_moderation_ban(kick_api: Kick, errors: list[Exception], query: str):
        channels = await kick_api.get_channels(slug=query)
        if not len(channels):
                pytest.skip(f"No channel returned for query: {query}")

        broadcaster = await kick_api.get_channels()
        if not len(broadcaster):
                pytest.skip("No actual broadcaster returned.")

        ban_data = await kick_api.delete_moderation_ban(
                channels[0].user_id,
                broadcaster[0].broadcaster_user_id,
        )
        expect(ban_data, DeleteModerationBanResponse, errors)


@pytest.mark.asyncio
async def test_generic_livestreams(kick_api: Kick, errors: list[Exception]):
        generic_livestreams = await kick_api.get_livestreams(sort="started_at")
        expect(generic_livestreams, list[LiveStream], errors)


@pytest.mark.parametrize("query", CHANNEL_QUERIES)
@pytest.mark.asyncio
async def test_livestreams(kick_api: Kick, errors: list[Exception], query: str):
        channels = await kick_api.get_channels(slug=query)
        if not len(channels):
                pytest.skip(f"No channel returned for query: {query}")

        livestreams = await kick_api.get_livestreams(channels[0].broadcaster_user_id)
        expect(livestreams, list[LiveStream], errors)


@pytest.mark.asyncio
async def test_livestream_stats(kick_api: Kick, errors: list[Exception]):
        livestream = await kick_api.get_livestream_stats()
        expect(livestream, LiveStreamStats, errors)


@pytest.mark.asyncio
async def test_public_key(kick_api: Kick, errors: list[Exception]):
        public_key = await kick_api.get_public_key()
        expect(public_key, str, errors)


@pytest.mark.asyncio
async def test_kicks_leaderboard(kick_api: Kick, errors: list[Exception]):
        leaderboard = await kick_api.get_kicks_leaderboard()
        expect(leaderboard, KicksLeaderboard, errors)

        top = 5
        leaderboard = await kick_api.get_kicks_leaderboard(top)
        expect(leaderboard, KicksLeaderboard, errors)

        assert len(leaderboard.lifetime) == 5
        assert len(leaderboard.month) == 5
        assert len(leaderboard.week) == 5


@pytest.mark.parametrize("query", CHANNEL_QUERIES)
@pytest.mark.asyncio
async def test_post_n_delete_event_subscription(kick_api: Kick, errors: list[Exception], query: str):
        channels = await kick_api.get_channels(slug=query)
        if not len(channels):
                pytest.skip(f"No channel returned for query: {query}")

        subscription_data = await kick_api.post_events_subscriptions(
                [EventSubEvents.CHANNEL_FOLLOW],
                channels[0].broadcaster_user_id,
        )
        if not len(subscription_data):
                pytest.fail("No subscription data returned")

        subscription = subscription_data[0]
        expect(subscription, PostEventSubscriptionResponse, errors)
        if not subscription.subscription_id:
                pytest.fail("No 'subscription_id' returned")

        subscriptions = await kick_api.get_events_subscriptions()
        expect(subscriptions, list[EventSubscription], errors)
        if not len(subscriptions):
                pytest.fail("Empty events subscriptions list returned")

        ok = await kick_api.delete_events_subscriptions([subscription.subscription_id])
        expect(ok, bool, errors)
