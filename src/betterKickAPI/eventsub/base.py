from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Awaitable
from dataclasses import dataclass
from itertools import batched
from logging import getLogger
from typing import TYPE_CHECKING, Callable, Generic, TypeVar, Union

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
        _CommonEventResponse,
)
from betterKickAPI.types import EventSubEvents, KickAPIException

if TYPE_CHECKING:
        from betterKickAPI.kick import Kick

__all__ = ["_E", "EventCallback", "EventSubBase"]
_E = TypeVar("_E", bound=_CommonEventResponse)
EventCallback = Callable[[_E], Union[Awaitable[None], None]]


@dataclass
class _EventSubInfo(Generic[_E]):
        sub_id: str
        response_type: type[_E]
        callback: EventCallback[_E]
        active: bool = False
        """
        Added because twitchAPI also has it. But it looks like it's never used (?).

        *Kept in case it's used in the future*
        """


class EventSubBase(ABC):
        def __init__(self, kick: Kick, logger_name: str, *, force_app_auth: bool = False) -> None:
                self.logger = getLogger(logger_name)
                self._kick = kick

                self.force_app_auth = force_app_auth
                """Use App Auth in all the EventSub related endpoints."""

                self._handlers: dict[str, _EventSubInfo] = {}
                self._handlers_lock = asyncio.Lock()

        @abstractmethod
        def start(self) -> None: ...

        @abstractmethod
        async def stop(self) -> None: ...

        # @abstractmethod
        # def _get_transport(self) -> dict: ...

        # @abstractmethod
        # async def _build_request_header(self) -> dict:
        #         pass

        # async def _api_post_request(self, session: AsyncClient, url: str, data: dict | None = None) -> Response:
        #         headers = await self._build_request_header()
        #         return await session.post(url, headers=headers, json=data)

        async def _add_callback(
                self,
                sub_id: str,
                callback: EventCallback[_E],
                response_type: type[_E],
        ) -> None:
                async with self._handlers_lock:
                        self._handlers[sub_id] = _EventSubInfo(
                                sub_id=sub_id,
                                response_type=response_type,
                                callback=callback,
                                active=True,
                        )

        @abstractmethod
        async def _subscribe(
                self,
                event: EventSubEvents,
                broadcaster_user_id: int,
                callback: EventCallback[_E],
                response_type: type[_E],
        ) -> str: ...

        # @abstractmethod
        # def _target_token(self) -> OAuthType: ...

        # async def _unsubscribe_hook(self, subscription_id: str) -> bool:
        #         return True

        async def unsubscribe_event(self, subscription_id: str) -> bool:
                """Unsubscribe from a specific event.

                Args:
                        subscription_id (str): The subscription ID.

                Returns:
                        bool: `True` if it was successful, otherwise `False`.
                """
                try:
                        await self._kick.delete_events_subscriptions([subscription_id], force_app_auth=self.force_app_auth)
                        async with self._handlers_lock:
                                self._handlers.pop(subscription_id, None)
                        # return await self._unsubscribe_hook(subscription_id)
                        return True
                except KickAPIException as e:
                        self.logger.warning("Failed to unsubscribe from %s: %s", subscription_id, e, exc_info=e)
                return False

        async def unsubscribe_all(self) -> None:
                """Unsubscribe from all subscriptions."""
                async with self._handlers_lock:
                        subs = await self._kick.get_events_subscriptions(force_app_auth=self.force_app_auth)
                        if not len(subs):
                                return

                        chunks = batched(subs, 50)
                        try:
                                for chunk in chunks:
                                        await self._kick.delete_events_subscriptions(
                                                [event_sub.id for event_sub in chunk],
                                                force_app_auth=self.force_app_auth,
                                        )
                        except KickAPIException as e:
                                self.logger.warning("Failed to unsubscribe from events: %s", e, exc_info=e)
                        self._handlers.clear()

        async def unsubscribe_all_local_knowns(self) -> None:
                """Unsubscribe from all subscriptions known to this client."""
                async with self._handlers_lock:
                        self.logger.debug("Unsubscribing from local events")
                        subs = list(self._handlers.values())
                        if not len(subs):
                                return

                        chunks = batched(subs, 50)
                        try:
                                for chunk in chunks:
                                        await self._kick.delete_events_subscriptions(
                                                [sub.sub_id for sub in chunk],
                                                force_app_auth=self.force_app_auth,
                                        )
                        except KickAPIException as e:
                                self.logger.warning("Failed to unsubscribe from local events: %s", e, exc_info=e)
                        self._handlers.clear()

        async def listen_chat_message_sent(
                self,
                broadcaster_user_id: int,
                callback: EventCallback[ChatMessageEvent],
        ) -> str:
                """Fired when a message has been sent in the broadcaster stream's chat.

                For more information, see here: https://docs.kick.com/events/event-types#chat-message

                Args:
                        broadcaster_user_id (int): The ID of the user's chat room you want to listen to.
                        callback (EventCallback[ChatMessageEvent]): Function for callback.

                Returns:
                        str: The subscription ID.
                """
                return await self._subscribe(EventSubEvents.CHAT_MESSAGE, broadcaster_user_id, callback, ChatMessageEvent)

        async def listen_channel_follow(
                self,
                broadcaster_user_id: int,
                callback: EventCallback[ChannelFollowEvent],
        ) -> str:
                """Fired when a user follows the broadcaster's channel.

                For more information, see here: https://docs.kick.com/events/event-types#channel-follow

                Args:
                        broadcaster_user_id (int): The ID of the user's channel you want to listen to.
                        callback (EventCallback[ChannelFollowEvent]): Function for callback.

                Returns:
                        str: The subscription ID.
                """
                return await self._subscribe(
                        EventSubEvents.CHANNEL_FOLLOW, broadcaster_user_id, callback, ChannelFollowEvent
                )

        async def listen_channel_subscription_gifts(
                self,
                broadcaster_user_id: int,
                callback: EventCallback[ChannelSubscriptionGiftsEvent],
        ) -> str:
                """Fired when a user gifts subscriptions to the broadcaster's channel.

                For more information, see here: https://docs.kick.com/events/event-types#channel-subscription-gifts

                Args:
                        broadcaster_user_id (int): The ID of the user's channel you want to listen to.
                        callback (EventCallback[ChannelSubscriptionGiftsEvent]): Function for callback.

                Returns:
                        str: The subscription ID.
                """
                return await self._subscribe(
                        EventSubEvents.CHANNEL_SUBSCRIPTION_GIFTS,
                        broadcaster_user_id,
                        callback,
                        ChannelSubscriptionGiftsEvent,
                )

        async def listen_channel_subscription_new(
                self,
                broadcaster_user_id: int,
                callback: EventCallback[ChannelSubscriptionNewEvent],
        ) -> str:
                """Fired when a user first subscribes to the broadcaster's channel.

                For more information, see here: https://docs.kick.com/events/event-types#channel-subscription-created

                Args:
                        broadcaster_user_id (int): The ID of the user's channel you want to listen to.
                        callback (EventCallback[ChannelSubscriptionNewEvent]): Function for callback.

                Returns:
                        str: The subscription ID.
                """
                return await self._subscribe(
                        EventSubEvents.CHANNEL_SUBSCRIPTION_CREATED,
                        broadcaster_user_id,
                        callback,
                        ChannelSubscriptionNewEvent,
                )

        async def listen_channel_subscription_renewal(
                self,
                broadcaster_user_id: int,
                callback: EventCallback[ChannelSubscriptionRenewalEvent],
        ) -> str:
                """Fired when a user's subscription to the broadcaster's channel is renewed.

                For more information, see here: https://docs.kick.com/events/event-types#channel-subscription-renewal

                Args:
                        broadcaster_user_id (int): The ID of the user's channel you want to listen to.
                        callback (EventCallback[ChannelSubscriptionRenewalEvent]): Function for callback.

                Returns:
                        str: The subscription ID.
                """
                return await self._subscribe(
                        EventSubEvents.CHANNEL_SUBSCRIPTION_RENEWAL,
                        broadcaster_user_id,
                        callback,
                        ChannelSubscriptionRenewalEvent,
                )

        async def listen_livestream_metadata_updated(
                self,
                broadcaster_user_id: int,
                callback: EventCallback[LivestreamMetadataUpdatedEvent],
        ) -> str:
                """Fired when the broadcaster stream's status has been updated.\n
                For example, the stream could have started or ended.

                For more information, see here: https://docs.kick.com/events/event-types#livestream-metadata-updated

                Args:
                        broadcaster_user_id (int): The ID of the user you want to listen to.
                        callback (EventCallback[LivestreamMetadataUpdatedEvent]): Function for callback.

                Returns:
                        str: The subscription ID.
                """
                return await self._subscribe(
                        EventSubEvents.LIVESTREAM_METADATA_UPDATED,
                        broadcaster_user_id,
                        callback,
                        LivestreamMetadataUpdatedEvent,
                )

        async def listen_livestream_status_updated(
                self,
                broadcaster_user_id: int,
                callback: EventCallback[LivestreamStatusUpdatedEvent],
        ) -> str:
                """Fired when the broadcaster stream's metadata has been updated.\n
                For example, the stream's title could have changed.

                For more information, see here: https://docs.kick.com/events/event-types#livestream-status-updated

                Args:
                        broadcaster_user_id (int): The ID of the user you want to listen to.
                        callback (EventCallback[LivestreamStatusUpdatedEvent]): Function for callback.

                Returns:
                        str: The subscription ID.
                """
                return await self._subscribe(
                        EventSubEvents.LIVESTREAM_STATUS_UPDATED,
                        broadcaster_user_id,
                        callback,
                        LivestreamStatusUpdatedEvent,
                )

        async def listen_moderation_banned(
                self,
                broadcaster_user_id: int,
                callback: EventCallback[ModerationBannedEvent],
        ) -> str:
                """Fired when a user has been banned from the broadcaster's channel.

                For more information, see here: https://docs.kick.com/events/event-types#moderation-banned

                Args:
                        broadcaster_user_id (int): The ID of the user's chat room you want to listen to.
                        callback (EventCallback[ModerationBannedEvent]): Function for callback.

                Returns:
                        str: The subscription ID.
                """
                return await self._subscribe(
                        EventSubEvents.MODERATION_BANNED,
                        broadcaster_user_id,
                        callback,
                        ModerationBannedEvent,
                )

        async def listen_kicks_gifted(
                self,
                broadcaster_user_id: int,
                callback: EventCallback[KicksGiftedEvent],
        ) -> str:
                """Fired when a user gifts kicks to the broadcaster's channel.

                For more information, see here: https://docs.kick.com/events/event-types#kicks-gifted

                Args:
                    broadcaster_user_id (int): The ID of the user's chat room you want to listen to.
                    callback (EventCallback[KicksGiftedEvent]): Function for callback.

                Returns:
                    str: The subscription ID.
                """
                return await self._subscribe(
                        EventSubEvents.KICKS_GIFTED,
                        broadcaster_user_id,
                        callback,
                        KicksGiftedEvent,
                )
