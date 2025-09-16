from __future__ import annotations

import asyncio
import multiprocessing
from collections import deque
from collections.abc import Awaitable
from dataclasses import dataclass
from json import JSONDecodeError
from logging import getLogger
from multiprocessing import managers, synchronize
from queue import Empty
from typing import TYPE_CHECKING, Any, Callable, Generic, TypeVar, Union

import orjson as json
from pydantic import ValidationError

from betterKickAPI.eventsub import utils
from betterKickAPI.eventsub.events import (
        ChannelFollowEvent,
        ChannelSubscriptionGiftsEvent,
        ChannelSubscriptionNewEvent,
        ChannelSubscriptionRenewalEvent,
        ChatMessageEvent,
        LivestreamMetadataUpdatedEvent,
        LivestreamStatusUpdatedEvent,
        ModerationBannedEvent,
        _CommonEventResponse,
)
from betterKickAPI.helper import ServerStatus, SSLOptions
from betterKickAPI.object.eventsub import WebhookVerificationHeaders
from betterKickAPI.servers import WebhookServer
from betterKickAPI.types import (
        EventSubSubscriptionError,
        KickAPIException,
        WebhookEvents,
)

if TYPE_CHECKING:
        from betterKickAPI.kick import Kick

__all__ = ["KickWebhook", "SSLOptions"]
E = TypeVar("E", bound=_CommonEventResponse)
EventCallback = Callable[[E], Union[Awaitable[None], None]]


@dataclass
class _EventSubscription(Generic[E]):
        sub_id: str
        response_type: type[E]
        callback: EventCallback[E]
        active: bool = False
        """
        Added because twitchAPI also has it. But it looks like it's never used (?).

        *Kept in case it's used in the future*
        """


@dataclass
class WebhookServerResponse:
        """Simple dataclass that contains the Webhook Endpoint ideal response."""

        status: int = 200
        text: str = ""


class KickWebhook:
        """EventSub integration for the Kick API."""

        def __init__(
                self,
                kick: Kick,
                *,
                public_key_pem: str | None = None,
                auto_fetch_public_key: bool = True,
                force_app_auth: bool = False,
                callback_loop: asyncio.AbstractEventLoop | None = None,
                msg_id_history_max_length: int = 50,
        ) -> None:
                """
                ## Dev note:
                        *If your `Kick` instance has user authentication, the Webhook will only be able to subscribe to
                        events linked to that user (the official Kick API overrides all the endpoints to use the
                        `broadcaster_user_id` linked to the user auth token).\n
                        If you want to subscribe to multiple broadcasters, please use a `Kick` instance with only app
                        authentication or set `force_app_auth` to `True`.*

                Args:
                        kick (Kick): An app authenticated instance of `Kick`.
                        public_key_pem (str | None, optional): Public Key that will be used to verify messages.
                                Defaults to `None`.
                        auto_fetch_public_key (bool, optional): If true, automatically fetches the public key from the API
                                endpoint. Defaults to `True`.
                        force_app_auth (bool): If true, app auth will be used in all the EventSub related endpoints.
                                Otherwise, user auth will be used if available. Defaults to `False`.
                        callback_loop (asyncio.AbstractEventLoop | None, optional): The asyncio event loop to be used for
                                callbacks. Defaults to `None`.\n
                                Set this if you or a library you use cares about which asyncio event loop is running the
                                callbacks.
                        msg_id_history_max_length (int, optional): The amount of messages being considered for the duplicate
                                message deduplication. Defaults to `50`.
                """
                self.logger = getLogger("kickAPI.webhook.KickWebhook")
                self._kick = kick

                self._public_key_pem = public_key_pem
                self._auto_fetch_public_key = auto_fetch_public_key
                self._force_app_auth = force_app_auth

                self._status = ServerStatus.CLOSED

                self.unsubscribe_on_stop = True
                """Unsubscribe all currently active Webhooks on calling `EventSub.stop()`."""
                self.unsubscribe_on_handler_not_found = True
                """Unsubscribe to received Webhook Events that don¿t have handlers set."""

                self._handlers: dict[str, _EventSubscription] = {}

                self.__process: multiprocessing.Process | None = None
                self.__stop_event: synchronize.Event = multiprocessing.Event()
                self._request_queue = multiprocessing.Queue()
                self._manager: managers.SyncManager = multiprocessing.Manager()
                self._responses: managers.DictProxy[Any, Any] = self._manager.dict()

                # self.__hook_loop =
                # self._task_callback = partial(done_task_callback, self.logger)
                self._callback_loop = callback_loop or asyncio.new_event_loop()

                self._seen_message_ids: deque = deque(maxlen=msg_id_history_max_length)

                self._lock = asyncio.Lock()

                self._background_tasks: set[asyncio.Task[bool]] = set()
                self._response_loop_task: asyncio.Task[None] | None = None

        async def get_public_key(self) -> str:
                if self._public_key_pem:
                        return self._public_key_pem

                if not self._auto_fetch_public_key:
                        raise RuntimeError("No public key configured and auto_fetch_public_key is disabled.")

                async with self._lock:
                        self._public_key_pem = await self._kick.get_public_key()
                return self._public_key_pem

        async def _response_loop(self) -> None:
                try:
                        while self._status not in (ServerStatus.CLOSED, ServerStatus.CLOSING):
                                try:
                                        item = await asyncio.get_running_loop().run_in_executor(
                                                None,
                                                self._request_queue.get,
                                                True,  # noqa: FBT003
                                                1.0,
                                        )
                                except Empty:
                                        continue
                                except Exception as e:  # noqa: BLE001
                                        self.logger.warning("Error reading from request queue: %s", e, exc_info=e)
                                        continue

                                if not item:
                                        continue

                                message_id, data_bytes, headers_dict = item
                                if not isinstance(data_bytes, bytes) or not isinstance(headers_dict, dict):
                                        self.logger.warning("Invalid data types in data or headers.")
                                        continue
                                headers = WebhookVerificationHeaders(**headers_dict)

                                try:
                                        response_obj = await self.handle_incoming(data_bytes, headers)
                                        response = {"status": response_obj.status, "text": response_obj.text}
                                except Exception as e:
                                        self.logger.exception("handle_incoming raised an exception for id %s", message_id)
                                        response = {"status": 500, "text": f"Handler error: {e}"}

                                self._responses[message_id] = response
                finally:
                        try:
                                while not self._request_queue.empty():
                                        message_id, data_bytes, headers_dict = self._request_queue.get_nowait()
                                        self._responses[message_id] = {"status": 503, "text": "Server shutting down"}
                        except Empty:
                                pass
                        self._manager.shutdown()

        async def start(
                self,
                port: int = 3000,
                host_binding: str = "127.0.0.1",
                # ssl_context: SSLContext | None = None,
                ssl_options: SSLOptions | None = None,
        ) -> None:
                """Starts the EventSub client.

                Args:
                        port (int, optional): The port on which this webhook should run. Defaults to 3000.
                        host_binding (str, optional): The host to bind the internal server to. Defaults to "127.0.0.1".
                        ssl_options (SSLOptions | None, optional): Optional SSLOptions to be used. Defaults to None.

                Raises:
                        RuntimeError: If EventSub is already running.
                """
                if self._status != ServerStatus.CLOSED:
                        raise RuntimeError("Already started")
                if self.__process:
                        return

                self._status = ServerStatus.OPENING
                self.__process = multiprocessing.Process(
                        target=WebhookServer,
                        args=(
                                port,
                                host_binding,
                                self._request_queue,
                                self._responses,
                                self.__stop_event,
                                ssl_options,
                        ),
                        # daemon=True,
                )
                self.__process.start()

                self._status = ServerStatus.OPENED
                self._response_loop_task = asyncio.create_task(self._response_loop())

        async def stop(self) -> None:
                """Stops the EventSub client.

                # Note:
                        This also unsubscribes from all known subscriptions if `unsubscribe_on_stop` is `True`.

                Raises:
                        RuntimeError: If EventSub is not running.
                """
                if self._status in (ServerStatus.CLOSED, ServerStatus.CLOSING) or not self.__process:
                        raise RuntimeError("KickWebhook is not running")

                self._status = ServerStatus.CLOSING
                self.logger.debug("Shutting down Webhook")

                async with self._lock:
                        await asyncio.gather(*self._background_tasks)

                if self._response_loop_task is not None:
                        self._response_loop_task.cancel()
                        try:
                                await self._response_loop_task
                        except asyncio.CancelledError:
                                pass
                        self._response_loop_task = None

                if self.unsubscribe_on_stop:
                        await self.unsubscribe_all_local_knowns()

                await asyncio.sleep(0.25)
                self.__stop_event.set()
                self.__process.join(5.0)
                if self.__process.is_alive():
                        self.logger.debug("Forcing terminate")
                        # self.__process.terminate()
                        self.__process.kill()
                        self.__process.join()

                self._status = ServerStatus.CLOSED
                self.logger.debug("Webhook shut down")
                self.__stop_event.clear()

        def _add_callback(
                self,
                sub_id: str,
                callback: EventCallback[E],
                response_type: type[E],
        ) -> None:
                self._handlers[sub_id] = _EventSubscription(
                        sub_id=sub_id,
                        response_type=response_type,
                        callback=callback,
                        active=True,
                )

        async def _subscribe(
                self,
                event: WebhookEvents,
                broadcaster_user_id: int,
                callback: EventCallback[E],
                response_type: type[E],
        ) -> str:
                self.logger.debug("Subscribing to %s version %d", event.value.name, event.value.version)
                event_subs = await self._kick.post_events_subscriptions(
                        [event],
                        broadcaster_user_id,
                        "webhook",
                        force_app_auth=self._force_app_auth,
                )
                subscription = event_subs[0]
                if subscription.error:
                        raise EventSubSubscriptionError(subscription.error)

                sub_id = subscription.subscription_id
                if not sub_id:
                        raise EventSubSubscriptionError("'subscription_id' is None")

                self.logger.debug("Subscription for %s version %d has id %s", event.value.name, event.value.version, sub_id)
                self._add_callback(sub_id, callback, response_type)
                # NOTE: Skipped because Kick Webhook doesn't sends subscription confirmations (I think)
                # https://github.com/Teekeks/pyTwitchAPI/blob/master/twitchAPI/eventsub/webhook.py#L299
                # if self.wait_for_subscription_confirm:
                return sub_id

        async def unsubscribe_event(self, subscription_id: str) -> bool:
                """Unsubscribe from a specific event.

                Args:
                        subscription_id (str): The subscription ID.

                Returns:
                        bool: `True` if it was successful, otherwise `False`.
                """
                try:
                        await self._kick.delete_events_subscriptions([subscription_id], force_app_auth=self._force_app_auth)
                        self._handlers.pop(subscription_id)
                        # return await self._unsubscribe_hook(subscription_id)
                        return True
                except KickAPIException as e:
                        self.logger.warning("Failed to unsubscribe from %d: %s", subscription_id, e, exc_info=e)
                return False

        async def unsubscribe_all(self) -> None:
                """Unsubscribe from all subscriptions."""
                subs = await self._kick.get_events_subscriptions(force_app_auth=self._force_app_auth)
                if not len(subs):
                        return
                try:
                        await self._kick.delete_events_subscriptions(
                                [event_sub.id for event_sub in subs],
                                force_app_auth=self._force_app_auth,
                        )
                except KickAPIException as e:
                        self.logger.warning("Failed to unsubscribe from events: %s", e, exc_info=e)
                self._handlers.clear()

        async def unsubscribe_all_local_knowns(self) -> None:
                """Unsubscribe from all subscriptions known to this client."""
                self.logger.debug("Unsubscribing from local events")
                try:
                        await self._kick.delete_events_subscriptions(
                                [sub.sub_id for sub in self._handlers.values()],
                                force_app_auth=self._force_app_auth,
                        )
                except KickAPIException as e:
                        self.logger.warning("Failed to unsubscribe from local events: %s", e, exc_info=e)
                self._handlers.clear()

        async def handle_incoming(self, data: bytes, headers: WebhookVerificationHeaders) -> WebhookServerResponse:
                """Public endpoint handler. In case you don't want to use the internal server.

                Args:
                        data (bytes): The request data in bytes.
                        headers (WebhookVerificationHeaders): A helper class to parse the headers.

                Returns:
                        WebhookServerResponse: A simple dataclass with `status` and `text` attributes.
                """
                resp = WebhookServerResponse()

                message_id = headers.kick_event_message_id
                signature = headers.kick_event_signature
                timestamp = headers.kick_event_message_timestamp
                # event_type = headers.kick_event_type
                subscription_id = headers.kick_event_subscription_id

                if not (message_id and timestamp and subscription_id and signature):
                        resp.status = 400
                        resp.text = "Missing required headers"
                        return resp

                if not utils.verify_signature(await self.get_public_key(), signature, message_id, timestamp, data):
                        resp.status = 403
                        resp.text = "Signature verification failed"
                        return resp

                async with self._lock:
                        if message_id in self._seen_message_ids:
                                resp.text = f"Duplicated ID: {message_id}. Discarded."
                                return resp

                        self._seen_message_ids.append(message_id)

                handler = self._handlers.get(subscription_id)
                if not handler:
                        resp.text = f"No handlers for '{headers.kick_event_type}' event with id: {subscription_id}."
                        if self.unsubscribe_on_handler_not_found:
                                resp.text = f"{resp.text} Unsubscribed."
                                task = asyncio.create_task(self.unsubscribe_event(subscription_id))
                                self._background_tasks.add(task)
                                task.add_done_callback(self._background_tasks.discard)
                        return resp

                try:
                        payload_obj = handler.response_type(**json.loads(data))
                except (JSONDecodeError, ValidationError) as e:
                        self.logger.warning("Payload parsing failed: %s", e, exc_info=e)
                        resp.status = 400
                        resp.text = f"Invalid payload: {e}"
                        return resp

                callback = handler.callback
                if asyncio.iscoroutinefunction(callback):
                        task = asyncio.create_task(callback(payload_obj))
                        task.add_done_callback(
                                lambda t: self.logger.warning("Callback failed: %s", t.exception(), exc_info=t.exception())
                                if t.exception()
                                else None
                        )
                else:

                        def _call_sync() -> None:
                                try:
                                        callback(payload_obj)
                                except Exception as e:  # noqa: BLE001
                                        self.logger.warning("Sync callback failed: %s", e, exc_info=e)

                        asyncio.get_running_loop().run_in_executor(None, _call_sync)

                return resp

        async def listen_chat_message_sent(
                self,
                broadcaster_user_id: int,
                callback: EventCallback[ChatMessageEvent],
        ) -> str:
                """A message is sent to the broadcaster's chat room.

                For more information, see here: https://docs.kick.com/events/event-types#chat-message

                Args:
                        broadcaster_user_id (int): The ID of the user's chat room you want to listen to.
                        callback (EventCallback[ChatMessageEvent]): Function for callback.

                Returns:
                        str: The subscription ID.
                """
                return await self._subscribe(WebhookEvents.CHAT_MESSAGE, broadcaster_user_id, callback, ChatMessageEvent)

        async def listen_channel_follow(
                self,
                broadcaster_user_id: int,
                callback: EventCallback[ChannelFollowEvent],
        ) -> str:
                """A user followed the broadcaster's channel.

                For more information, see here: https://docs.kick.com/events/event-types#channel-follow

                Args:
                        broadcaster_user_id (int): The ID of the user's channel you want to listen to.
                        callback (EventCallback[ChannelFollowEvent]): Function for callback.

                Returns:
                        str: The subscription ID.
                """
                return await self._subscribe(WebhookEvents.CHANNEL_FOLLOW, broadcaster_user_id, callback, ChannelFollowEvent)

        async def listen_channel_subscription_gifts(
                self,
                broadcaster_user_id: int,
                callback: EventCallback[ChannelSubscriptionGiftsEvent],
        ) -> str:
                """A user gifted one or more subscriptions to the broadcaster's channel.

                For more information, see here: https://docs.kick.com/events/event-types#channel-subscription-gifts

                Args:
                        broadcaster_user_id (int): The ID of the user's channel you want to listen to.
                        callback (EventCallback[ChannelSubscriptionGiftsEvent]): Function for callback.

                Returns:
                        str: The subscription ID.
                """
                return await self._subscribe(
                        WebhookEvents.CHANNEL_SUBSCRIPTION_GIFTS,
                        broadcaster_user_id,
                        callback,
                        ChannelSubscriptionGiftsEvent,
                )

        async def listen_channel_subscription_new(
                self,
                broadcaster_user_id: int,
                callback: EventCallback[ChannelSubscriptionNewEvent],
        ) -> str:
                """A user subscribed for the first time to the broadcaster's channel.

                For more information, see here: https://docs.kick.com/events/event-types#channel-subscription-created

                Args:
                        broadcaster_user_id (int): The ID of the user's channel you want to listen to.
                        callback (EventCallback[ChannelSubscriptionNewEvent]): Function for callback.

                Returns:
                        str: The subscription ID.
                """
                return await self._subscribe(
                        WebhookEvents.CHANNEL_SUBSCRIPTION_CREATED,
                        broadcaster_user_id,
                        callback,
                        ChannelSubscriptionNewEvent,
                )

        async def listen_channel_subscription_renewal(
                self,
                broadcaster_user_id: int,
                callback: EventCallback[ChannelSubscriptionRenewalEvent],
        ) -> str:
                """A user resubscribed to the broadcaster's channel.

                For more information, see here: https://docs.kick.com/events/event-types#channel-subscription-renewal

                Args:
                        broadcaster_user_id (int): The ID of the user's channel you want to listen to.
                        callback (EventCallback[ChannelSubscriptionRenewalEvent]): Function for callback.

                Returns:
                        str: The subscription ID.
                """
                return await self._subscribe(
                        WebhookEvents.CHANNEL_SUBSCRIPTION_RENEWAL,
                        broadcaster_user_id,
                        callback,
                        ChannelSubscriptionRenewalEvent,
                )

        async def listen_livestream_metadata_updated(
                self,
                broadcaster_user_id: int,
                callback: EventCallback[LivestreamMetadataUpdatedEvent],
        ) -> str:
                """The broadcaster livestream metadata has changed.

                For more information, see here: https://docs.kick.com/events/event-types#livestream-metadata-updated

                Args:
                        broadcaster_user_id (int): The ID of the user you want to listen to.
                        callback (EventCallback[LivestreamMetadataUpdatedEvent]): Function for callback.

                Returns:
                        str: The subscription ID.
                """
                return await self._subscribe(
                        WebhookEvents.LIVESTREAM_METADATA_UPDATED,
                        broadcaster_user_id,
                        callback,
                        LivestreamMetadataUpdatedEvent,
                )

        async def listen_livestream_status_updated(
                self,
                broadcaster_user_id: int,
                callback: EventCallback[LivestreamStatusUpdatedEvent],
        ) -> str:
                """The broadcaster live status has changed.

                For more information, see here: https://docs.kick.com/events/event-types#livestream-status-updated

                Args:
                        broadcaster_user_id (int): The ID of the user you want to listen to.
                        callback (EventCallback[LivestreamStatusUpdatedEvent]): Function for callback.

                Returns:
                        str: The subscription ID.
                """
                return await self._subscribe(
                        WebhookEvents.LIVESTREAM_STATUS_UPDATED,
                        broadcaster_user_id,
                        callback,
                        LivestreamStatusUpdatedEvent,
                )

        async def listen_moderation_banned(
                self,
                broadcaster_user_id: int,
                callback: EventCallback[ModerationBannedEvent],
        ) -> str:
                """A moderator has banned a user in the broadcaster's chat room.

                For more information, see here: https://docs.kick.com/events/event-types#moderation-banned

                Args:
                        broadcaster_user_id (int): The ID of the user's chat room you want to listen to.
                        callback (EventCallback[ModerationBannedEvent]): Function for callback.

                Returns:
                        str: The subscription ID.
                """
                return await self._subscribe(
                        WebhookEvents.MODERATION_BANNED,
                        broadcaster_user_id,
                        callback,
                        ModerationBannedEvent,
                )
