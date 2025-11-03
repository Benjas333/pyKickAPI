from __future__ import annotations

import asyncio
import base64
import hashlib
import multiprocessing
import os
import secrets
import webbrowser
from logging import getLogger
from logging.handlers import QueueListener
from pathlib import PurePath
from typing import TYPE_CHECKING, Any, Callable, Literal

import aiofiles
import orjson as json
from aiohttp import ClientSession

from betterKickAPI import helper
from betterKickAPI.constants import (
        KICK_API_BASE_URL,
        KICK_AUTH_BASE_URL,
        Endpoints,
        ServerStatus,
)
from betterKickAPI.object.api import TokenIntrospection
from betterKickAPI.servers import AuthServer
from betterKickAPI.types import (
        InvalidRefreshTokenException,
        KickAPIException,
        MissingScopeException,
        OAuthScope,
)

if TYPE_CHECKING:
        from collections.abc import Awaitable
        from multiprocessing import managers, synchronize

        from betterKickAPI.kick import Kick

__all__ = [
        "UserAuthenticationStorageHelper",
        "UserAuthenticator",
        "refresh_access_token",
        "revoke_token",
        "validate_token",
]


async def refresh_access_token(
        refresh_token: str,
        app_id: str,
        app_secret: str,
        session: ClientSession | None = None,
        auth_base_url: str = KICK_AUTH_BASE_URL,
) -> tuple[str, str]:
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        body = {
                "refresh_token": refresh_token,
                "client_id": app_id,
                "client_secret": app_secret,
                "grant_type": "refresh_token",
        }
        url = helper.clean_url(auth_base_url, Endpoints.Auth.TOKEN)
        ses = session if session is not None else ClientSession()
        async with ses.post(url, data=body, headers=headers) as r:
                data = json.loads(await r.read())
        if session is None:
                await ses.close()
        if "error" in data:
                raise InvalidRefreshTokenException(data["error"])
        r.raise_for_status()
        return data["access_token"], data["refresh_token"]


async def validate_token(
        access_token: str,
        session: ClientSession | None = None,
        auth_base_url: str = KICK_API_BASE_URL,
) -> TokenIntrospection:
        headers = {"Authorization": f"Bearer {access_token}"}
        url = helper.clean_url(auth_base_url, Endpoints.API.TOKEN_INTROSPECT)
        ses = session if session is not None else ClientSession()
        async with ses.post(url, headers=headers) as r:
                if r.status == 401:
                        return TokenIntrospection()
                r.raise_for_status()
                data = json.loads(await r.read())
        if session is None:
                await ses.close()
        return TokenIntrospection(**data.get("data", {}))


async def revoke_token(
        token: str,
        token_hint_type: Literal["access_token", "refresh_token"],
        session: ClientSession | None = None,
        auth_base_url: str = KICK_AUTH_BASE_URL,
) -> bool:
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        params = {"token": token, "token_type_hint": token_hint_type}
        url = helper.clean_url(auth_base_url, Endpoints.Auth.REVOKE_TOKEN)
        _url = helper.build_url(url, params)
        ses = session if session is not None else ClientSession()
        async with ses.post(_url, headers=headers) as r:
                resp = r.status == 200
        if session is None:
                await ses.close()
        return resp


# class CodeFlow:
#         def __init__(
#                 self,
#                 kick: Kick,
#                 scopes: list[OAuthScope],
#                 auth_base_url: str = KICK_AUTH_BASE_URL,
#         ) -> None:
#                 self._kick = kick
#                 self._client_id = kick.app_id
#                 self._scopes = scopes
#                 self.logger = getLogger("kickAPI.oauth.code_flow")
#                 self.auth_base_url = auth_base_url
#                 self._device_code: str | None = None
#                 self._expires_in: datetime | None = None

#         async def get_code(self) -> tuple[str, str]:
#                 async with ClientSession(timeout=self._kick.session_timeout) as session:
#                         data = {"client_id": self._client_id, "scopes": helper.build_scope(self._scopes)}
#                         result = await session.post(self.auth_base_url + "device", data=data)
#                         data = json.loads(result.content)
#                         self._device_code = data["device_code"]
#                         self._expires_in = datetime.now() + timedelta(seconds=data["expires_in"])
#                         await result.aclose()
#                         return data["user_code"], data["verification_uri"]


#         async def wait_for_auth_complete(self) -> tuple[str, str]:
#                 if self._device_code is None or self._expires_in is None:
#                         raise ValueError("Please start the code flow first using CodeFlow.get_code()")
#                 request_data = {
#                         "client_id": self._client_id,
#                         "scopes": helper.build_scope(self._scopes),
#                         "device_code": self._device_code,
#                         "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
#                 }
#                 async with ClientSession(timeout=self._kick.session_timeout) as session:
#                         while True:
#                                 if datetime.now() > self._expires_in:
#                                         raise TimeoutError("Timed out waiting for auth complete")
#                                 result = await session.post(self.auth_base_url + "token", data=request_data)
#                                 data = json.loads(result.content)
#                                 await result.aclose()
#                                 if data.get("access_token") is not None:
#                                         self._device_code = None
#                                         self._expires_in = None
#                                         return data["access_token"], data["refresh_token"]
#                                 await asyncio.sleep(1)


class UserAuthenticator:
        """Simple to use client for the Kick User authentication flow."""

        def __init__(
                self,
                kick: Kick,
                scopes: list[OAuthScope],
                url: str = "http://localhost:36571",
                host: str = "127.0.0.1",
                port: int = 36571,
                auth_base_url: str = KICK_AUTH_BASE_URL,
        ) -> None:
                """Simple to use cliente for the Kick User authentication flow.

                Args:
                        kick (Kick): A `Kick` instance.
                        scopes (list[OAuthScope]): List of desired OAuth scopes.
                        url (str, optional): The reachable URL that will be opened in the browser. Defaults to "http://localhost:36571".
                        host (str, optional): The host the webserver will bind to. Defaults to "127.0.0.1".
                        port (int, optional): The port that will be used for the webserver. Defaults to `36571`.
                        auth_base_url (str, optional): The URL to the Kick API auth server. Defaults to `KICK_AUTH_BASE_URL`.
                """
                self._kick = kick
                self._client_id = kick.app_id

                self.scopes = scopes
                self.logger = getLogger("kickAPI.oauth")
                self.url = url
                self.auth_base_url = auth_base_url
                self.port = port
                self.host = host
                self.state = str(helper.get_uuid())
                self.code_verifier = self._generate_code_verifier()
                self.code_challenge = self._generate_code_challenge(self.code_verifier)

                self._status = ServerStatus.CLOSED
                self._auth_code: str | None = None

                self._process: multiprocessing.Process | None = None
                self._stop_event: synchronize.Event = multiprocessing.Event()
                self._auth_code_changed_event: synchronize.Event = multiprocessing.Event()
                self._manager: managers.SyncManager = multiprocessing.Manager()
                self._shared: managers.DictProxy[Any, Any] = self._manager.dict()
                self._logger_queue = multiprocessing.Queue()
                self._logger_listener = QueueListener(self._logger_queue, *getLogger().handlers)

        def _generate_code_verifier(self) -> str:
                code_verifier = secrets.token_urlsafe(64)
                if len(code_verifier) > 128:
                        code_verifier = code_verifier[:128]
                return code_verifier

        def _generate_code_challenge(self, code_verifier: str) -> str:
                code_challenge = hashlib.sha256(code_verifier.encode()).digest()
                return base64.urlsafe_b64encode(code_challenge).decode().rstrip("=")

        def _build_auth_url(self) -> str:
                params = {
                        "client_id": self._kick.app_id,
                        "redirect_uri": self.url,
                        "response_type": "code",
                        "scope": helper.build_scope(self.scopes),
                        "state": self.state,
                        "code_challenge": self.code_challenge,
                        "code_challenge_method": "S256",
                }
                return helper.build_url(helper.clean_url(self.auth_base_url, Endpoints.Auth.AUTHORIZATION), params)

        async def _start(self) -> None:
                if self._status != ServerStatus.CLOSED:
                        raise RuntimeError("Already started")
                if self._process:
                        return
                self._status = ServerStatus.OPENING
                # self._stop_event = multiprocessing.Event()
                # self._manager = multiprocessing.Manager()
                # self._shared = self._manager.dict()
                self._logger_listener.start()

                self._process = multiprocessing.Process(
                        target=AuthServer,
                        args=(
                                self.port,
                                self.host,
                                self.state,
                                self._logger_queue,
                                self._shared,
                                self._stop_event,
                                self._auth_code_changed_event,
                        ),
                        # daemon=True,
                )
                self._process.start()
                self._status = ServerStatus.OPENED

        def stop(self) -> None:
                """Manually stop the webserver."""
                if not self._process:
                        return

                self._status = ServerStatus.CLOSING
                self.logger.info("Shutting down OAuth WebServer")
                self._stop_event.set()
                self._process.join(5.0)
                if self._process.is_alive():
                        self.logger.debug("Forcing terminate")
                        # self._process.terminate()
                        self._process.kill()
                        self._process.join()

                self._logger_listener.stop()
                self._status = ServerStatus.CLOSED
                self.logger.debug("OAuth WebServer shut down")
                self._auth_code_changed_event.clear()
                self._stop_event.clear()

        @property
        def auth_url(self) -> str:
                """The URL that will authenticate the app, used for headless server environments.

                Returns:
                        str: The URL
                """
                return self._build_auth_url()

        # async def mock_authentication(self, user_id: str) -> str:
        #         https://github.com/Teekeks/pyTwitchAPI/blob/master/twitchAPI/oauth.py#L405

        async def authenticate(
                self,
                token_callback: Callable[[str | None, str | None], None] | None = None,
                auth_code_callback: Callable[[str], None] | None = None,
                auth_code: str | None = None,
                browser_name: str | None = None,
                browser_new: int = 2,
                *,
                use_browser: bool = True,
                auth_url_callback: Callable[[str], Awaitable[None]] | None = None,
        ) -> tuple[str, str] | None:
                """Start the user authentication flow.\n
                If `token_callback` is not set, authenticate will wait till the authentication process finished and then
                return the `access_token` and the `refresh_token`.
                If `user_token` is set, it will be used instead of launching the webserver and opening the browser.

                Args:
                        token_callback (Callable[[str  |  None, str  |  None], None] | None, optional): Function to call once
                                the authentication finished. Defaults to `None`.
                        auth_code_callback (Callable[[str], None] | None, optional): Function to call once the `auth_code` is
                                received. Defaults to `None`.\n
                                Added because twitchAPI calls `token_callback` too when receiving the `auth_code` for some
                                reason.
                        auth_code (str | None, optional): Code obtained from kick to request the access and refresh token.
                                Defaults to `None`.
                        browser_name (str | None, optional): The browser that should be used. Defaults to `None`.\n
                                `None` means that the system default is used.\n
                                See the `register webbrowser documentation`_ for more info.
                        browser_new (int, optional): Controls in which way the link will be opened in the browser.
                                Defaults to `2`.\n
                                See the `open webbrowser documentation`_ for more info.
                        use_browser (bool, optional): Controls if a browser should be opened. Defaults to `True`.\n
                                If set to `False`, the browser will not be opened and the URL to be opened will either be
                                printed to the info log or send to the specified callback function
                                (controlled by `auth_url_callback`)
                        auth_url_callback (Callable[[str], Awaitable[None]] | None, optional): An async callback that will be
                                called with the url to be used for the authentication flow should `user_browser` be `False`.
                                Defaults to `None`.\n
                                If left as `None`, the URL will instead be printed to the info log.

                Raises:
                        KickAPIException: Authentication flow did not returned any `auth_code`.
                        KickAPIException: Authentication failed.
                        MissingScopeException: Authentication succeeded, but has missing OAuth scopes.

                Returns:
                        tuple[str, str] | None: None if `token_callback` is set, otherwise `access_token` and
                                `refresh_token`.

                .. _register webbrowser documentation:
                        https://docs.python.org/3/library/webbrowser.html#webbrowser.register
                .. _open webbrowser documentation:
                        https://docs.python.org/3/library/webbrowser.html#webbrowser.open
                """
                # self.stop()
                self._auth_code = None
                auth_url = self._build_auth_url()

                if auth_code is not None:
                        self._auth_code = auth_code
                else:
                        await self._start()

                        if use_browser:
                                browser = webbrowser.get(browser_name)
                                browser.open(auth_url, new=browser_new)
                        elif auth_url_callback is not None:
                                await auth_url_callback(auth_url)
                        else:
                                self.logger.info("To authenticate open: %s", auth_url)

                        await asyncio.to_thread(self._auth_code_changed_event.wait)
                        self._auth_code = self._shared.get("code")
                        if self._auth_code is None:
                                raise KickAPIException("Authentication failed. Code is None")
                        if auth_code_callback is not None:
                                auth_code_callback(self._auth_code)

                body = {
                        "client_id": self._client_id,
                        "client_secret": self._kick.app_secret,
                        "code": self._auth_code,
                        "grant_type": "authorization_code",
                        "redirect_uri": self.url,
                        "code_verifier": self.code_verifier,
                }
                headers = {"Content-Type": "application/x-www-form-urlencoded"}
                url = helper.build_url(helper.clean_url(self.auth_base_url, Endpoints.Auth.TOKEN), {})
                async with (
                        ClientSession(timeout=self._kick.session_timeout) as session,
                        session.post(url, data=body, headers=headers) as response,
                ):
                        data: dict = json.loads(await response.read())

                self.stop()
                token, refresh = data.get("access_token"), data.get("refresh_token")
                if token_callback is None:
                        if token is None or refresh is None:
                                raise KickAPIException(f"Authentication failed:\n{data}")
                        scopes = data.get("scope", "").split(" ")
                        missing_scopes = [scope for scope in self.scopes if scope not in scopes]
                        if missing_scopes:
                                raise MissingScopeException(
                                        f"Authentication has missing scope(s): {', '.join(missing_scopes)}"
                                )
                        return token, refresh
                # This actually does not make sense lol.
                # Should return (token, refresh) every time and call the callback from outside if there's one
                # instead of passing a parameter to the function.
                # Only kept in order to maintain parity with twitchAPI lib
                # TL;DR: Unnecessary logic.
                if auth_code is not None:
                        token_callback(token, refresh)
                return None


class UserAuthenticationStorageHelper:
        """Helper for automating the generation and storage of a user auth token.

        Basic example use::

                kick = await Kick(APP_ID, APP_SECRET)
                helper = UserAuthenticationStorageHelper(kick, TARGET_SCOPES)
                await helper.bind()
        """

        def __init__(
                self,
                kick: Kick,
                scopes: list[OAuthScope],
                storage_path: PurePath | None = None,
                auth_generator_func: Callable[[Kick, list[OAuthScope]], Awaitable[tuple[str, str]]] | None = None,
                auth_base_url: str = KICK_AUTH_BASE_URL,
        ) -> None:
                self.kick = kick
                self.logger = getLogger("kickAPI.oauth.storage_helper")
                self._target_scopes = scopes
                self.storage_path = storage_path or PurePath("user_token.json")
                self.auth_generator = auth_generator_func or self._default_auth_gen
                self.auth_base_url = auth_base_url

        async def _default_auth_gen(self, kick: Kick, scopes: list[OAuthScope]) -> tuple[str, str]:
                auth = UserAuthenticator(kick, scopes, auth_base_url=self.auth_base_url)
                return await auth.authenticate()  # type: ignore

        async def _update_stored_token(self, token: str, refresh_token: str) -> None:
                self.logger.info("User token got refreshed and stored")
                async with aiofiles.open(self.storage_path, "wb") as f:
                        await f.write(json.dumps({"token": token, "refresh": refresh_token}))

        async def bind(self) -> None:
                """Bind the helper to the provided instance of kick and sets the user authentication."""
                self.kick.user_auth_refresh_callback = self._update_stored_token
                needs_auth = True
                if os.path.exists(self.storage_path):
                        try:
                                async with aiofiles.open(self.storage_path, "rb") as f:
                                        credentials = json.loads(await f.read())
                                await self.kick.set_user_authentication(
                                        token=credentials["token"],
                                        scope=self._target_scopes,
                                        refresh_token=credentials["refresh"],
                                )
                        except Exception as e:  # noqa: BLE001
                                self.logger.info("Stored token invalid (reason: %s), refreshing...", e)
                        else:
                                needs_auth = False
                if needs_auth:
                        token, refresh_token = await self.auth_generator(self.kick, self._target_scopes)
                        async with aiofiles.open(self.storage_path, "wb") as f:
                                await f.write(json.dumps({"token": token, "refresh": refresh_token}))
                        await self.kick.set_user_authentication(
                                token=token,
                                scope=self._target_scopes,
                                refresh_token=refresh_token,
                        )
