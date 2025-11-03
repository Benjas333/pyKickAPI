from __future__ import annotations

import asyncio
import multiprocessing
from collections import deque
from dataclasses import dataclass
from logging import getLogger
from logging.handlers import QueueListener
from multiprocessing import managers, synchronize
from queue import Empty
from typing import TYPE_CHECKING, Any

import orjson as json
from pydantic import AliasChoices, AliasGenerator, ConfigDict, ValidationError, dataclasses

from betterKickAPI.constants import ServerStatus
from betterKickAPI.eventsub import utils
from betterKickAPI.eventsub.base import _E, EventCallback, EventSubBase
from betterKickAPI.object.base import KickObject
from betterKickAPI.servers import WebhookServer
from betterKickAPI.types import (
        EventSubEvents,
        EventSubSubscriptionError,
)

if TYPE_CHECKING:
        from betterKickAPI.kick import Kick

__all__ = ["KickWebhook", "SSLOptions", "VerificationHeaders"]


@dataclass
class WebhookServerResponse:
        """Simple dataclass that contains the Webhook Endpoint ideal response."""

        status: int = 200
        text: str = ""


@dataclass
class SSLOptions:
        key_file_name: str | None = None
        cert_file_name: str | None = None
        passphrase: str | None = None
        dh_params_file_name: str | None = None
        ca_file_name: str | None = None
        ssl_ciphers: str | None = None
        ssl_prefer_low_memory_usage: int = 0


def _parse_header_style(key: str) -> str:
        return key.title().replace("_", "-")


def _validation_alias(field_name: str) -> AliasChoices:
        title = _parse_header_style(field_name)
        return AliasChoices(title, title.lower(), field_name.title(), field_name)


@dataclasses.dataclass(
        config=ConfigDict(
                serialize_by_alias=True,
                validate_assignment=True,
                extra="allow",
                alias_generator=AliasGenerator(validation_alias=_validation_alias, serialization_alias=_parse_header_style),
        )
)
class VerificationHeaders(KickObject):
        kick_event_message_id: str
        kick_event_subscription_id: str
        kick_event_signature: str
        kick_event_message_timestamp: str
        kick_event_type: str
        kick_event_version: str


class KickWebhook(EventSubBase):
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
                super().__init__(kick, "kickAPI.eventsub.webhook", force_app_auth=force_app_auth)

                self._public_key_pem = public_key_pem
                self._auto_fetch_public_key = auto_fetch_public_key

                self._status = ServerStatus.CLOSED

                self.unsubscribe_on_stop = True
                """Unsubscribe all currently active Webhook Events on calling `KickWebhook.stop()`. Defaults to `True`."""
                self.unsubscribe_on_handler_not_found = True
                """Unsubscribe to received Webhook Events that don't have handlers set. Defaults to `True`."""

                self.__process: multiprocessing.Process | None = None
                self.__stop_event: synchronize.Event = multiprocessing.Event()
                self._request_queue = multiprocessing.Queue()
                self._manager: managers.SyncManager = multiprocessing.Manager()
                self._responses: managers.DictProxy[Any, Any] = self._manager.dict()
                self._logger_queue = multiprocessing.Queue()
                self._logger_listener = QueueListener(self._logger_queue, *getLogger().handlers)

                # self.__hook_loop =
                # self._task_callback = partial(done_task_callback, self.logger)
                self._callback_loop = callback_loop or asyncio.new_event_loop()

                self._seen_message_ids: deque = deque(maxlen=msg_id_history_max_length)

                self._lock = asyncio.Lock()

                self._background_tasks: set[asyncio.Task[bool]] = set()
                self._response_loop_task: asyncio.Task[None] | None = None
                self._shutdown_cmd = "SHUTDOWN-SERVER"

        async def get_public_key(self) -> str:
                async with self._lock:
                        if self._public_key_pem:
                                return self._public_key_pem

                        if not self._auto_fetch_public_key:
                                raise RuntimeError("No public key configured and auto_fetch_public_key is disabled.")

                        self._public_key_pem = await self._kick.get_public_key()
                return self._public_key_pem

        async def _response_loop(self) -> None:
                try:
                        while True:
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

                                message_id, data, headers = item
                                if message_id == self._shutdown_cmd:
                                        break
                                if not isinstance(data, bytes) or not isinstance(headers, dict):
                                        msg = "Invalid data types from data or headers."
                                        self.logger.warning(msg)
                                        self._responses[message_id] = {"status": 400, "text": msg}
                                        continue

                                try:
                                        response_obj = await self.handle_incoming(data, headers)
                                        response = {"status": response_obj.status, "text": response_obj.text}
                                except Exception as e:
                                        self.logger.exception("handle_incoming raised an exception for id %s", message_id)
                                        response = {"status": 500, "text": f"Handler error: {e}"}

                                self._responses[message_id] = response
                finally:
                        try:
                                while not self._request_queue.empty():
                                        message_id = self._request_queue.get_nowait()[0]
                                        self._responses[message_id] = {"status": 503, "text": "Server shutting down"}
                        except Empty:
                                pass
                        self._manager.shutdown()

        def start(
                self,
                port: int = 3330,
                host_binding: str = "127.0.0.1",
                # ssl_context: SSLContext | None = None,
                endpoint: str = "/callback",
                ssl_options: SSLOptions | None = None,
        ) -> None:
                """Starts the EventSub client.

                Args:
                        port (int, optional): The port on which this webhook should run. Defaults to `3330`.
                        host_binding (str, optional): The host to bind the internal server to. Defaults to "127.0.0.1".
                        endpoint (str, optional): The endpoint that will handle the webhook events. Defaults to "/callback".
                        ssl_options (SSLOptions | None, optional): Optional SSLOptions to be used. Defaults to None.

                Raises:
                        RuntimeError: If EventSub is already running.
                """
                if self._status != ServerStatus.CLOSED:
                        raise RuntimeError("Already started")
                if self.__process:
                        return

                self._status = ServerStatus.OPENING
                self._response_loop_task = asyncio.create_task(self._response_loop())
                self._logger_listener.start()
                self.__process = multiprocessing.Process(
                        target=WebhookServer,
                        args=(
                                port,
                                host_binding,
                                self._logger_queue,
                                self._request_queue,
                                self._responses,
                                self.__stop_event,
                                endpoint,
                                ssl_options,
                        ),
                        # daemon=True,
                )
                self.__process.start()

                self._status = ServerStatus.OPENED

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

                if self.unsubscribe_on_stop:
                        await self.unsubscribe_all_local_knowns()

                self._request_queue.put_nowait((self._shutdown_cmd, None, None))

                if self._response_loop_task is not None:
                        await self._response_loop_task
                        self._response_loop_task = None

                async with self._lock:
                        await asyncio.gather(*self._background_tasks)

                await asyncio.sleep(0.25)

                self.__stop_event.set()
                self.__process.join(5.0)
                if self.__process.is_alive():
                        self.logger.debug("Forcing terminate")
                        # self.__process.terminate()
                        self.__process.kill()
                        self.__process.join()

                self._logger_listener.stop()

                self._status = ServerStatus.CLOSED
                self.logger.debug("Webhook shut down")
                self.__stop_event.clear()

        async def _subscribe(
                self,
                event: EventSubEvents,
                broadcaster_user_id: int,
                callback: EventCallback[_E],
                response_type: type[_E],
        ) -> str:
                self.logger.debug("Subscribing to %s version %d", event.value.name, event.value.version)
                event_subs = await self._kick.post_events_subscriptions(
                        [event],
                        broadcaster_user_id,
                        "webhook",
                        force_app_auth=self.force_app_auth,
                )
                subscription = event_subs[0]
                if subscription.error:
                        raise EventSubSubscriptionError(subscription.error)

                sub_id = subscription.subscription_id
                if not sub_id:
                        raise EventSubSubscriptionError("'subscription_id' is None")

                self.logger.debug("Subscription for %s version %d has id %s", event.value.name, event.value.version, sub_id)
                await self._add_callback(sub_id, callback, response_type)
                # NOTE: Skipped because Kick Webhook doesn't sends subscription confirmations (I think)
                # https://github.com/Teekeks/pyTwitchAPI/blob/master/twitchAPI/eventsub/webhook.py#L299
                # if self.wait_for_subscription_confirm:
                return sub_id

        async def handle_incoming(  # noqa: C901
                self,
                data: bytes,
                headers: dict | VerificationHeaders,
        ) -> WebhookServerResponse:
                """Public endpoint handler. In case you don't want to run the internal server from the library.

                Args:
                        data (bytes): The request data in bytes.
                        headers (dict | VerificationHeaders): Either the raw headers dict or an instance of the
                                `VerificationHeaders` helper class.

                Returns:
                        WebhookServerResponse: A simple dataclass with `status` and `text` attributes.
                """
                resp = WebhookServerResponse()

                if not isinstance(headers, VerificationHeaders):
                        try:
                                headers_obj = VerificationHeaders(**headers)
                        except ValidationError as e:
                                resp.status = 400
                                resp.text = f"Validation error: {e}"
                                self.logger.warning(resp.text, exc_info=e)
                                return resp
                else:
                        headers_obj = headers

                message_id = headers_obj.kick_event_message_id
                subscription_id = headers_obj.kick_event_subscription_id
                timestamp = headers_obj.kick_event_message_timestamp
                signature = headers_obj.kick_event_signature

                if not (message_id and subscription_id and timestamp and signature):
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
                        resp.text = f"No handlers for '{headers_obj.kick_event_type}' event with id: {subscription_id}."
                        if self.unsubscribe_on_handler_not_found and self._status != ServerStatus.CLOSING:
                                resp.text = f"{resp.text} Unsubscribed."
                                self.logger.warning(resp.text)
                                task = asyncio.create_task(self.unsubscribe_event(subscription_id))
                                self._background_tasks.add(task)
                                task.add_done_callback(self._background_tasks.discard)
                        return resp

                try:
                        payload_obj = handler.response_type(**json.loads(data))
                except (json.JSONDecodeError, ValidationError) as e:
                        self.logger.warning("Payload parsing failed: %s", e, exc_info=e)
                        resp.status = 400
                        resp.text = f"Invalid payload: {e}"
                        return resp

                if asyncio.iscoroutinefunction(handler.callback):
                        task = asyncio.create_task(handler.callback(payload_obj))
                        task.add_done_callback(
                                lambda t: self.logger.exception("Callback failed: %s", t.exception(), exc_info=t.exception())
                                if t.exception()
                                else None
                        )
                else:

                        def _call_sync() -> None:
                                try:
                                        handler.callback(payload_obj)
                                except Exception as e:
                                        self.logger.exception("Sync callback failed: %s", e)

                        asyncio.get_running_loop().run_in_executor(None, _call_sync)

                return resp
