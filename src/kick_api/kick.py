from __future__ import annotations

import asyncio
from json import JSONDecodeError
from logging import getLogger
from typing import (
        TYPE_CHECKING,
        Any,
        Callable,
        Literal,
        Self,
        TypeVar,
        overload,
)

import httpx
import orjson as json

from kick_api import helper
from kick_api.constants import (
        KICK_API_BASE_URL,
        KICK_AUTH_BASE_URL,
        Endpoints,
        ResultType,
)
from kick_api.object import api
from kick_api.object.base import AsyncIterData, AsyncIterKickObject, KickObject
from kick_api.types import (
        InvalidTokenException,
        KickAPIException,
        KickAuthorizationException,
        KickBackendException,
        KickResourceNotFound,
        MissingAppSecretException,
        MissingScopeException,
        OAuthScope,
        OAuthType,
        UnauthorizedException,
        WebhookEvents,
)

if TYPE_CHECKING:
        from collections.abc import AsyncGenerator, Awaitable, Generator, Mapping, Sequence

T = TypeVar("T", bound=KickObject)

__all__ = ["Kick"]


class Kick:
        """
        Kick API client.
        """

        def __init__(
                self,
                app_id: str,
                app_secret: str | None = None,
                *,
                authenticate_app: bool = True,
                # target_app_auth_scope: list[OAuthScope] | None = None,
                base_url: str = KICK_API_BASE_URL,
                auth_base_url: str = KICK_AUTH_BASE_URL,
                session_timeout: int = 300,
        ) -> None:
                """

                Args:
                    app_id (str): Your app id.
                    app_secret (str | None, optional): Your app secret. Defaults to `None`.\n
                        Leave as `None` if you only want to use User Authentication.
                    authenticate_app (bool, optional): If true, auto generate an app token on startup. Defaults to `True`.
                    base_url (str, optional): The URL to the Kick API. Defaults to `KICK_API_BASE_URL`.
                    auth_base_url (str, optional): The URL to the Kick API auth server. Defaults to `KICK_AUTH_BASE_URL`.
                    session_timeout (int, optional): Override the time in seconds before any request times out.
                        Defaults to `300`.
                """
                self.app_id = app_id
                self.app_secret = app_secret
                self.logger = getLogger("kickAPI.Kick")
                self.user_auth_refresh_callback: Callable[[str, str], Awaitable[None]] | None = None
                """If set, gets called whenever a user auth token gets refreshed."""
                self.app_auth_refresh_callback: Callable[[str], Awaitable[None]] | None = None
                """If set, gets called whenever an app auth token gets refreshed."""
                self.session_timeout = session_timeout

                self._app_auth_token: str | None = None
                # self._app_auth_scope: list[OAuthScope] = []
                self._has_app_auth = False

                self._user_auth_token: str | None = None
                self._user_auth_refresh_token: str | None = None
                self._user_auth_scope: list[OAuthScope] = []
                self._has_user_auth = False

                self.auto_refresh_auth: bool = True
                """If set to true, auto refresh the auth token once it expires."""
                self._authenticate_app = authenticate_app
                # self._target_app_scope = target_app_auth_scope
                self.base_url = base_url
                self.auth_base_url = auth_base_url
                self._user_token_refresh_lock = False
                self._app_token_refresh_lock = False

        def __await__(self) -> Generator[Any, Any, Self]:
                if self._authenticate_app:
                        task = asyncio.create_task(
                                # self._target_app_scope if self._target_app_scope is not None else []
                                self.authenticate_app()
                        )

                        yield from task
                return self

        @staticmethod
        async def close() -> None:
                """Gracefully close the connection to the Kick API."""
                await asyncio.sleep(0.25)

        @property
        def user_auth_scope(self) -> list[OAuthScope]:
                """The set User oauth scopes.

                Returns:
                    list[OAuthScope]: List of User Oauth Scopes.
                """
                return self._user_auth_scope

        @property
        def app_auth_token(self) -> str | None:
                """The app token that the api uses or None when not authenticated.

                Returns:
                    str | None: App Token.
                """
                return self._app_auth_token

        @property
        def user_auth_token(self) -> str | None:
                """The current user auth token, `None` if no user authentication is set.

                Returns:
                    str | None: User Token.
                """
                return self._user_auth_token

        async def get_refreshed_user_auth_token(self) -> str | None:
                """Validates the current set user auth token and returns it.

                Note:
                    Will re-auth if token is invalid.

                Returns:
                    str | None: User Token.
                """
                if self._user_auth_token is None:
                        return None
                from .oauth import validate_token

                token_introspect = await validate_token(self._user_auth_token, auth_base_url=self.base_url)
                if not token_introspect.active:
                        await self.refresh_used_token()
                return self._user_auth_token

        async def get_refreshed_app_token(self) -> str | None:
                if self._app_auth_token is None:
                        return None
                from .oauth import validate_token

                token_introspect = await validate_token(self._app_auth_token, auth_base_url=self.base_url)
                if not token_introspect.active:
                        await self._refresh_app_token()
                return self._app_auth_token

        @property
        def used_token(self) -> str | None:
                """The currently used token.\n
                Can be either the app or user auth token or `None` if no authentication is set.

                Returns:
                    str | None: The currently used auth token or `None`.
                """
                return self._user_auth_token if self._has_user_auth else self.app_auth_token

        def has_required_auth(self, required_type: OAuthType, required_scope: list[OAuthScope]) -> bool:
                if required_type == OAuthType.NONE:
                        return True
                if required_type == OAuthType.EITHER:
                        return self.has_required_auth(OAuthType.USER, required_scope) or self.has_required_auth(
                                OAuthType.APP, required_scope
                        )
                if required_type == OAuthType.USER:
                        if not self._has_user_auth:
                                return False
                        return all(scope in self._user_auth_scope for scope in required_scope)
                if required_type == OAuthType.APP:
                        # NOTE: Scopes checking skipped because (I think) Kick endpoints with app auth don't use any scope
                        # if not self._has_app_auth:
                        #         return False
                        # return all(scope in self._app_auth_scope for scope in required_scope)
                        return self._has_app_auth
                return False

        def _get_used_either_auth(
                self,
                required_scope: list[OAuthScope],
        ) -> tuple[bool, OAuthType, str | None, list[OAuthScope]]:
                if self.has_required_auth(OAuthType.USER, required_scope):
                        return True, OAuthType.USER, self._user_auth_token, self._user_auth_scope
                if self.has_required_auth(OAuthType.APP, required_scope):
                        return True, OAuthType.APP, self._app_auth_token, []
                return False, OAuthType.NONE, None, []

        def _generate_headers(
                self,
                auth_type: OAuthType,
                required_scope: list[OAuthScope],
                *,
                is_json: bool = False,
        ) -> dict[str, str]:
                # https://github.com/Teekeks/pyTwitchAPI/blob/master/twitchAPI/twitch.py#L292
                headers = {}
                if auth_type == OAuthType.EITHER:
                        has_auth, _, token, _ = self._get_used_either_auth(required_scope)
                        if not has_auth:
                                raise UnauthorizedException("No authorization with correct scope set!")
                        headers["Authorization"] = f"Bearer {token}"
                elif auth_type == OAuthType.APP:
                        if not self._has_app_auth:
                                raise UnauthorizedException("Require app authentication!")
                        # Scopes checking skipped because (I think) Kick endpoints with app auth doesn't require any scope
                        headers["Authorization"] = f"Bearer {self._app_auth_token}"
                elif auth_type == OAuthType.USER:
                        if not self._has_user_auth:
                                raise UnauthorizedException("Require user authentication!")
                        for scope in required_scope:
                                if scope in self._user_auth_scope:
                                        continue
                                raise MissingScopeException(f"Require user auth scope: {scope}")
                        headers["Authorization"] = f"Bearer {self._user_auth_token}"

                if is_json:
                        headers["Content-Type"] = "application/json"
                return headers

        async def refresh_used_token(self) -> None:
                """Refreshes the currently used token"""
                if not self._has_user_auth:
                        await self._refresh_app_token()
                        return

                from kick_api.oauth import refresh_access_token

                if self._user_token_refresh_lock:
                        while self._user_token_refresh_lock:
                                await asyncio.sleep(0.1)
                                return

                self.logger.debug("refreshing user token")
                self._user_token_refresh_lock = True
                self._user_auth_token, self._user_auth_refresh_token = await refresh_access_token(
                        self._user_auth_refresh_token,  # type: ignore
                        self.app_id,
                        self.app_secret,  # type: ignore
                        auth_base_url=self.auth_base_url,
                )
                self._user_token_refresh_lock = False

                if self.user_auth_refresh_callback is None:
                        return
                await self.user_auth_refresh_callback(self._user_auth_token, self._user_auth_refresh_token)

        async def _refresh_app_token(self) -> None:
                if self._app_token_refresh_lock:
                        while self._app_token_refresh_lock:
                                await asyncio.sleep(0.1)
                                return

                self.logger.debug("refreshing app token")
                self._app_token_refresh_lock = True
                await self._generate_app_token()
                self._app_token_refresh_lock = False
                if self.app_auth_refresh_callback is not None:
                        await self.app_auth_refresh_callback(self._app_auth_token)  # type: ignore

        async def _check_request_return(  # noqa: C901
                self,
                session: httpx.AsyncClient,
                response: httpx.Response,
                method: str,
                url: str,
                auth_type: OAuthType,
                required_scope: list[OAuthScope],
                *,
                body_json: dict | None = None,
                custom_headers: dict[str, str] | None = None,
                retries: int = 1,
        ) -> httpx.Response:
                if response.status_code == 503:
                        if retries < 1:
                                raise KickBackendException(f"The Kick API returned a server error ({response.status_code}).")

                        self.logger.warning("Failed with status %d, retrying...", response.status_code)
                        await response.aclose()
                        return await self._api_request(
                                method,
                                session,
                                url,
                                auth_type,
                                required_scope,
                                body_json=body_json,
                                custom_headers=custom_headers,
                                retries=retries - 1,
                        )

                default = "Message error not provided"
                if response.status_code == 401:
                        if retries < 1:
                                msg = json.loads(response.content).get("message", default)
                                self.logger.warning(
                                        'Failed with status %d and can\'t refresh. Message: "%s"',
                                        response.status_code,
                                        msg,
                                )
                                raise UnauthorizedException(msg)

                        if not self.auto_refresh_auth:
                                msg = json.loads(response.content).get("message", default)
                                self.logger.warning(
                                        'Failed with status %d and auto-refresh is disabled. Message: "%s"',
                                        response.status_code,
                                        msg,
                                )
                                raise UnauthorizedException(msg)

                        self.logger.warning("Failed with status %d, trying to refresh token...", response.status_code)
                        await response.aclose()
                        await self.refresh_used_token()
                        return await self._api_request(
                                method,
                                session,
                                url,
                                auth_type,
                                required_scope,
                                body_json=body_json,
                                custom_headers=custom_headers,
                                retries=retries - 1,
                        )

                if response.status_code == 500:
                        msg = json.loads(response.content).get("message", default)
                        self.logger.warning('Failed with status %d. Message: "%s"', response.status_code, msg)
                        raise KickBackendException(f'Internal Server Error: {msg}')

                if response.status_code == 400:
                        msg = json.loads(response.content).get("message", default)
                        raise KickAPIException(f'Bad Request ({response.status_code}): {msg}')

                if response.status_code == 404:
                        try:
                                msg = json.loads(response.content).get("message", default)
                        except JSONDecodeError:
                                msg = None
                        raise KickResourceNotFound(msg)

                if response.status_code == 429:
                        self.logger.warning('Reached rate limit, waiting for reset')
                        await asyncio.sleep(5) # Magic number because there's no rate limit header in kick API responses
                        await response.aclose()
                        return await self._api_request(
                                method,
                                session,
                                url,
                                auth_type,
                                required_scope,
                                body_json=body_json,
                                custom_headers=custom_headers,
                                retries=retries,
                        )

                response.raise_for_status()
                return response

        async def _api_request(
                self,
                method: str,
                session: httpx.AsyncClient,
                url: str,
                auth_type: OAuthType,
                required_scope: list[OAuthScope],
                *,
                body_json: dict | None = None,
                custom_headers: dict[str, str] | None = None,
                retries: int = 1,
        ) -> httpx.Response:
                headers = self._generate_headers(
                        auth_type,
                        required_scope,
                        is_json=body_json is not None,
                )
                headers.update(custom_headers or {})
                self.logger.debug("making %s request to %s", method, url)
                r = await session.request(method, url, headers=headers, json=body_json)
                return await self._check_request_return(
                        session,
                        r,
                        method,
                        url,
                        auth_type,
                        required_scope,
                        body_json=body_json,
                        custom_headers=custom_headers,
                        retries=retries,
                )

        async def _build_generator(
                self,
                method: str,
                endpoint: api._Endpoint,
                url_params: dict,
                auth_type: OAuthType,
                auth_scope: list[OAuthScope],
                return_type: type[T],
                *,
                body_json: dict | None = None,
                custom_headers: dict[str, str] | None = None,
                split_lists: bool = False,
                error_handler: Mapping[int, BaseException] | None = None,
        ) -> AsyncGenerator[T, None]:
                _page = url_params.get("page", 1)
                _first = True
                url = helper.clean_url(self.base_url, endpoint)
                async with httpx.AsyncClient(timeout=self.session_timeout) as ses:
                        while _first or _page is not None:
                                _first = False
                                url_params["page"] = _page
                                _url = helper.build_url(url, url_params, remove_none=True, split_lists=split_lists)
                                r = await self._api_request(
                                        method,
                                        ses,
                                        _url,
                                        auth_type,
                                        auth_scope,
                                        body_json=body_json,
                                        custom_headers=custom_headers,
                                )
                                if error_handler is not None and r.status_code in error_handler:
                                        raise error_handler[r.status_code]
                                data = json.loads(r.content)
                                await r.aclose()
                                entries = data.get("data", [])
                                _page = None if not len(entries) else (_page or 1) + 1
                                for entry in entries:
                                        yield return_type(**entry)

        async def _build_iter_result(
                self,
                method: str,
                endpoint: api._Endpoint,
                url_params: dict,
                auth_type: OAuthType,
                auth_scope: list[OAuthScope],
                return_type: type[AsyncIterKickObject[T]],
                *,
                body_json: dict | None = None,
                custom_headers: dict[str, str] | None = None,
                split_lists: bool = False,
                in_data: bool = False,
        ) -> AsyncIterKickObject[T]:
                url = helper.clean_url(self.base_url, endpoint)
                _url = helper.build_url(url, url_params, remove_none=True, split_lists=split_lists)
                async with httpx.AsyncClient(timeout=self.session_timeout) as ses:
                        r = await self._api_request(
                                method, ses, _url, auth_type, auth_scope, body_json=body_json, custom_headers=custom_headers
                        )
                        data = json.loads(r.content)
                        await r.aclose()
                url_params.setdefault("page", 1)
                if in_data:
                        data = data["data"]
                iter_data = AsyncIterData(
                        req=self._api_request,
                        method=method,
                        url=url,
                        param=url_params,
                        split=split_lists,
                        auth_t=auth_type,
                        auth_s=auth_scope,
                        body=body_json,
                        custom_headers=custom_headers,
                        in_data=in_data,
                )
                return return_type(iter_data=iter_data, **data)

        @overload
        async def _build_result(
                self,
                method: str,
                endpoint: api._Endpoint,
                url_params: dict,
                auth_type: OAuthType,
                auth_scope: list[OAuthScope],
                return_type: type[T],
                *,
                body_json: dict | None = None,
                custom_headers: dict[str, str] | None = None,
                split_lists: bool = False,
                get_from_data: bool = True,
                result_type: ResultType = ResultType.RETURN_TYPE,
                error_handler: Mapping[int, BaseException] | None = None,
        ) -> T: ...

        @overload
        async def _build_result(
                self,
                method: str,
                endpoint: api._Endpoint,
                url_params: dict,
                auth_type: OAuthType,
                auth_scope: list[OAuthScope],
                return_type: type[dict],
                *,
                body_json: dict | None = None,
                custom_headers: dict[str, str] | None = None,
                split_lists: bool = False,
                get_from_data: bool = True,
                result_type: ResultType = ResultType.RETURN_TYPE,
                error_handler: Mapping[int, BaseException] | None = None,
        ) -> dict: ...

        @overload
        async def _build_result(
                self,
                method: str,
                endpoint: api._Endpoint,
                url_params: dict,
                auth_type: OAuthType,
                auth_scope: list[OAuthScope],
                return_type: type[str],
                *,
                body_json: dict | None = None,
                custom_headers: dict[str, str] | None = None,
                split_lists: bool = False,
                get_from_data: bool = True,
                result_type: ResultType = ResultType.RETURN_TYPE,
                error_handler: Mapping[int, BaseException] | None = None,
        ) -> str: ...

        @overload
        async def _build_result(
                self,
                method: str,
                endpoint: api._Endpoint,
                url_params: dict,
                auth_type: OAuthType,
                auth_scope: list[OAuthScope],
                return_type: type[Sequence[T]],
                *,
                body_json: dict | None = None,
                custom_headers: dict[str, str] | None = None,
                split_lists: bool = False,
                get_from_data: bool = True,
                result_type: ResultType = ResultType.RETURN_TYPE,
                error_handler: Mapping[int, BaseException] | None = None,
        ) -> Sequence[T]: ...

        @overload
        async def _build_result(
                self,
                method: str,
                endpoint: api._Endpoint,
                url_params: dict,
                auth_type: OAuthType,
                auth_scope: list[OAuthScope],
                return_type: type[Sequence[str]],
                *,
                body_json: dict | None = None,
                custom_headers: dict[str, str] | None = None,
                split_lists: bool = False,
                get_from_data: bool = True,
                result_type: ResultType = ResultType.RETURN_TYPE,
                error_handler: Mapping[int, BaseException] | None = None,
        ) -> Sequence[str]: ...

        @overload
        async def _build_result(
                self,
                method: str,
                endpoint: api._Endpoint,
                url_params: dict,
                auth_type: OAuthType,
                auth_scope: list[OAuthScope],
                return_type: None,
                *,
                body_json: dict | None = None,
                custom_headers: dict[str, str] | None = None,
                split_lists: bool = False,
                get_from_data: bool = True,
                result_type: ResultType = ResultType.RETURN_TYPE,
                error_handler: Mapping[int, BaseException] | None = None,
        ) -> None: ...

        async def _build_result(
                self,
                method: str,
                endpoint: api._Endpoint,
                url_params: dict,
                auth_type: OAuthType,
                auth_scope: list[OAuthScope],
                return_type: type[T] | type[str] | type[dict] | type[Sequence[T]] | type[Sequence[str]] | None,
                *,
                body_json: dict | None = None,
                custom_headers: dict[str, str] | None = None,
                split_lists: bool = False,
                get_from_data: bool = True,
                result_type: ResultType = ResultType.RETURN_TYPE,
                error_handler: Mapping[int, BaseException] | None = None,
        ) -> T | int | str | dict | Sequence[T] | Sequence[str] | None:
                url = helper.clean_url(self.base_url, endpoint)
                async with httpx.AsyncClient(timeout=self.session_timeout) as ses:
                        _url = helper.build_url(url, url_params, remove_none=True, split_lists=split_lists)
                        r = await self._api_request(
                                method,
                                ses,
                                _url,
                                auth_type,
                                auth_scope,
                                body_json=body_json,
                                custom_headers=custom_headers,
                        )
                        # self.logger.info(r.content)
                        if error_handler is not None and r.status_code in error_handler:
                                raise error_handler[r.status_code]
                        if result_type == ResultType.STATUS_CODE:
                                return r.status_code
                        if result_type == ResultType.TEXT:
                                return r.text

                        if return_type is not None:
                                data = json.loads(r.content)
                                if isinstance(return_type, dict):
                                        return data
                                origin = return_type.__origin__ if hasattr(return_type, "__origin__") else None  # type: ignore
                                if origin is list:
                                        c = return_type.__args__[0]  # type: ignore
                                        return [x if isinstance(x, c) else c(**x) for x in data["data"]]
                                if not get_from_data:
                                        return return_type(**data)

                                d = data["data"]
                                if not isinstance(d, list):
                                        return return_type(**d)

                                if len(d):
                                        return return_type(**d[0])
                                return None
                        return None

        async def _generate_app_token(self) -> None:
                if self.app_secret is None:
                        raise MissingAppSecretException()
                headers = {"Content-Type": "application/x-www-form-urlencoded"}
                body = {"client_id": self.app_id, "client_secret": self.app_secret, "grant_type": "client_credentials"}
                url = helper.clean_url(self.auth_base_url, Endpoints.Auth.TOKEN)
                async with httpx.AsyncClient(timeout=self.session_timeout) as ses:
                        r = await ses.post(url, data=body, headers=headers)
                if r.status_code != 200:
                        raise KickAuthorizationException(f"Authentication failed with code {r.status_code} ({r.text})")
                try:
                        data = json.loads(r.content)
                        self._app_auth_token = data["access_token"]
                except ValueError as err:
                        raise KickAuthorizationException("Authentication response did not have a valid JSON body") from err
                except KeyError as err:
                        raise KickAuthorizationException("Authentication response did not contain access_token") from err

        async def authenticate_app(
                self,
                # scope: list[OAuthScope],
        ) -> None:
                """Authenticate with a fresh generated app token.

                Dev Note:
                    `scope` param removed because (apparently) Kick app tokens don't require scopes. Only user tokens.
                """
                # self._app_auth_scope = scope
                await self._generate_app_token()
                self._has_app_auth = True

        async def set_app_authentication(
                self,
                token: str,
                # scope: list[OAuthScope],
        ) -> None:
                """Set an app token, most likely only used for testing purposes.

                Dev Note:
                    `scope` param removed because (apparently) Kick app tokens don't require scopes. Only user tokens.

                Args:
                    token (str): The app token.
                """
                self._app_auth_token = token
                # self._app_auth_scope = scope
                self._has_app_auth = True

        async def _user_validation(
                self,
                token: str,
                scope: list[OAuthScope],
                refresh_token: str | None = None,
        ) -> tuple[str, str | None]:
                from .oauth import refresh_access_token, validate_token

                token_introspect = await validate_token(token, auth_base_url=self.base_url)
                if not token_introspect.active and refresh_token is not None:
                        token, refresh_token = await refresh_access_token(
                                refresh_token,
                                self.app_id,
                                self.app_secret,  # type: ignore
                                auth_base_url=self.auth_base_url,
                        )
                        if self.user_auth_refresh_callback is not None:
                                await self.user_auth_refresh_callback(token, refresh_token)
                        token_introspect = await validate_token(token, auth_base_url=self.base_url)
                if not token_introspect.active:
                        raise InvalidTokenException("Token is not active")
                if token_introspect.token_type != "user":
                        raise InvalidTokenException("Not a user oauth token")
                if token_introspect.client_id != self.app_id:
                        raise InvalidTokenException("client_id does not match")
                scopes_raw = token_introspect.scope
                scopes = (
                        scopes_raw.split(" ")
                        if isinstance(scopes_raw, str)
                        else scopes_raw
                        if isinstance(scopes_raw, list)
                        else []
                )
                missing_scopes = [scope for scope in scope if scope not in scopes]
                if missing_scopes:
                        raise MissingScopeException(f"Missing scopes: {', '.join(missing_scopes)}")
                return token, refresh_token

        async def set_user_authentication(
                self,
                *,
                token: str,
                scope: list[OAuthScope],
                refresh_token: str | None = None,
                validate: bool = True,
        ) -> None:
                """Set a user token to be used.

                Args:
                    token (str): The generated user token.
                    scope (list[OAuthScope]): List of Authorization Scopes that the given user token has.\n
                        Has to be provided if `auto_refresh_auth` is `True`.
                    refresh_token (str | None, optional): The generated refresh token. Defaults to `None`.
                    validate (bool, optional): If true, validate the set token for being a user auth token and having the
                        required scope. Defaults to `True`.

                Raises:
                    ValueError: `refresh_token` must be provided if `auto_refresh_auth` is `True`.
                    ValueError: If given token is missing one of the required scopes.
                """
                if refresh_token is None and self.auto_refresh_auth:
                        raise ValueError("refresh_token must be provided if auto_refresh_auth is True")
                if scope is None:
                        raise MissingScopeException("scope must be provided")
                if validate:
                        token, refresh_token = await self._user_validation(token, scope, refresh_token)

                self._user_auth_token = token
                self._user_auth_refresh_token = refresh_token
                self._user_auth_scope = scope
                self._has_user_auth = True

        # ===================================================================================================================
        # API calls
        # ===================================================================================================================

        async def get_categories(self, query: str, page: int = 1) -> AsyncGenerator[api.Category, None]:
                """Get Categories based on the search word. Returns up to 100 results at a time.

                For detailed documentation, see here: https://docs.kick.com/apis/categories#get-categories

                Args:
                    query (str): Search query.
                    page (int, optional): Page. Defaults to `1`.\n
                        **Dev note: The library already handles pagination on its own.**

                Raises:
                    ValueError: `page` must be greater than 0.
                """
                if page < 1:
                        raise ValueError("'page' must be int >= 1")

                params = {"q": query, "page": page}
                async for category in self._build_generator(
                        "GET",
                        Endpoints.API.CATEGORIES,
                        params,
                        OAuthType.EITHER,
                        [],
                        api.Category,
                        split_lists=True,
                ):
                        yield category

        async def get_category(self, category_id: int | str) -> api.Category:
                """Get Category based on the id.

                For detailed documentation, see here: https://docs.kick.com/apis/categories#get-categories-category_id

                Args:
                    category_id (int | str): Category ID.
                """
                return await self._build_result(
                        "GET",
                        Endpoints.API.category(category_id),
                        {},
                        OAuthType.EITHER,
                        [],
                        api.Category,
                )

        async def token_introspect(self, token: str) -> api.TokenIntrospection:
                """Get information about the token that is passed in via the Authorization header.
                This function is implements part of the on the OAuth 2.0 spec for token introspection.
                Find the full spec here: https://datatracker.ietf.org/doc/html/rfc7662
                When active=`False` there is no additional information added in the response.

                For detailed documentation, see here: https://docs.kick.com/apis/users#post-token-introspect

                Args:
                    token (str): Token to introspect.
                """
                return await self._build_result(
                        "POST",
                        Endpoints.API.TOKEN_INTROSPECT,
                        {},
                        OAuthType.NONE,
                        [],
                        api.TokenIntrospection,
                        custom_headers={"Authorization": f"Bearer {token}"},
                )

        async def get_users(self, user_id: int | list[int] | None = None) -> Sequence[api.User]:
                """Retrieve user information based on provided user IDs.

                For detailed documentation, see here: https://docs.kick.com/apis/users#get-users

                Args:
                    user_id (int | list[int] | None, optional): User IDs. Defaults to `None`.\n
                        If no user IDs are specified, returns the information for the currently authorized user.
                """
                # _id = [user_id] if isinstance(user_id, int) else user_id
                params = {"id": user_id}
                return await self._build_result(
                        "GET",
                        Endpoints.API.USERS,
                        params,
                        OAuthType.USER if not user_id else OAuthType.EITHER,
                        [OAuthScope.USER_READ],
                        list[api.User],
                        split_lists=True,
                )

        async def get_channels(
                self,
                *,
                broadcaster_user_id: int | list[int] | None = None,
                slug: str | list[str] | None = None,
        ) -> Sequence[api.Channel]:
                """Retrieve channel information based on provided broadcaster user IDs or channel slugs.

                Note:
                    If none of the parameters are provided, returns the information for the currently authenticated user.

                For detailed documentation, see here: https://docs.kick.com/apis/channels#get-channels

                Args:
                    broadcaster_user_id (int | list[int] | None, optional): Broadcaster User IDs. Defaults to `None`.\n
                        Note: cannot be used with `slug`.
                    slug (str | list[str] | None, optional): Channel slugs. Defaults to `None`.\n
                        Note: cannot be used with `broadcaster_user_id`.

                Raises:
                    ValueError: `broadcaster_user_id` must be max 50 entries.
                    ValueError: `slug` must be max 50 entries.
                    ValueError: Each `slug` must be max 25 characters.
                    ValueError: Cannot provide both `broadcaster_user_id` and `slug` at the same time.
                """
                _user_id = [broadcaster_user_id] if isinstance(broadcaster_user_id, int) else broadcaster_user_id
                if _user_id and len(_user_id) > 50:
                        raise ValueError("'broadcaster_user_id' must be max 50 entries")

                _slug = [slug] if isinstance(slug, str) else slug
                if _slug and len(_slug) > 50:
                        raise ValueError("'slug' must be max 50 entries")

                for slg in _slug or []:
                        if len(slg) < 26:
                                continue
                        raise ValueError(f"'{slug}' is too large (max 25 characters)")

                if _user_id and _slug:
                        raise ValueError("Cannot provide both 'broadcaster_user_id' and 'slug' at the same time")

                params = {"broadcaster_user_id": _user_id, "slug": _slug}
                return await self._build_result(
                        "GET",
                        Endpoints.API.CHANNELS,
                        params,
                        OAuthType.USER if not (_user_id or _slug) else OAuthType.EITHER,
                        [OAuthScope.CHANNEL_READ],
                        list[api.Channel],
                        split_lists=True,
                )

        async def patch_channel(
                self,
                category_id: int | None = None,
                custom_tags: list[str] | None = None,
                stream_title: str | None = None,
        ) -> bool:
                """Updates livestream metadata for a channel.

                For detailed documentation, see here: https://docs.kick.com/apis/channels#patch-channels

                Args:
                    category_id (int | None, optional): Category ID. Defaults to `None`.
                    custom_tags (list[str] | None, optional): Custom Tags. Defaults to `None`.
                    stream_title (str | None, optional): Stream Title. Defaults to `None`.
                """
                body = {"category_id": category_id, "custom_tags": custom_tags, "stream_title": stream_title}
                return (
                        await self._build_result(
                                "PATCH",
                                Endpoints.API.CHANNELS,
                                {},
                                OAuthType.USER,
                                [OAuthScope.CHANNEL_WRITE],
                                None,
                                body_json=body,
                                result_type=ResultType.STATUS_CODE,
                        )
                        == 204
                )

        async def post_chat_message(
                self,
                content: str,
                msg_type: Literal["user", "bot"] = "bot",
                broadcaster_user_id: int | None = None,
                reply_to_message_id: str | None = None,
        ) -> api.PostChatMessageResponse:
                """Post a chat message to a channel as a user or a bot.

                Note:
                    The channel where the message will be posted is the same as the currently authenticated user.
                    In other words, the one linked to the token.

                For detailed documentation, see here: https://docs.kick.com/apis/chat#post-chat

                Args:
                    content (str): Message content
                    msg_type (Literal[&quot;user&quot;, &quot;bot&quot;], optional): Defaults to "bot".\n
                        When sending as a `user`, the `broadcaster_user_id` is required.\n
                        Whereas when sending as a `bot`, the `broadcaster_user_id` is not required and is ignored.\n
                        As a `bot`, the message will always be sent to the channel attached to your token.
                    broadcaster_user_id (int | None, optional): Broadcaster user ID. Defaults to `None`.\n
                        **Dev note: At the moment, the API only supports the linked to the actual token.**
                    reply_to_message_id (str | None, optional): Message ID to reply. Defaults to `None`.

                Raises:
                    ValueError: `content` must be max 500 characters.
                    ValueError: to send a message as 'user' you must provide a `broadcaster_user_id`.
                """
                if len(content) > 500:
                        raise ValueError("'content' must be max 500 characters")

                if msg_type == "user" and broadcaster_user_id is None:
                        raise ValueError("To send a message as 'user' you must provide a 'broadcaster_user_id'")

                body = {
                        "broadcaster_user_id": broadcaster_user_id,
                        "content": content,
                        "reply_to_message_id": reply_to_message_id,
                        "type": msg_type,
                }
                return await self._build_result(
                        "POST",
                        Endpoints.API.CHAT_MESSAGE,
                        {},
                        OAuthType.USER,
                        [OAuthScope.CHAT_WRITE],
                        api.PostChatMessageResponse,
                        body_json=body,
                )

        async def post_moderation_ban(
                self,
                user_id: int,
                broadcaster_user_id: int,
                duration: int | None = None,
                reason: str | None = None,
        ) -> api.PostModerationBanResponse:
                """Ban or timeout a user from participating in a broadcaster's chat room.

                For detailed documentation, see here: https://docs.kick.com/apis/moderation#post-moderation-bans

                Args:
                    user_id (int): User ID of the user that will be banned/timed out.
                    broadcaster_user_id (int): Broadcaster User ID of the broadcaster's chat room.\n
                        **Dev note: At the moment, the API only supports the linked to the actual token.**
                    duration (int | None, optional): Timeout period in minutes. Defaults to `None`.\n
                        To ban a user, don't include this field.
                    reason (str | None, optional): Ban/timeout reason. Defaults to `None`.

                Raises:
                    ValueError: `duration` must be between 1 and 10080.
                    ValueError: `reason` must be max 100 characters.
                """
                if duration and not (0 < duration < 10081):
                        raise ValueError("'duration' must be between 1 and 10080")

                if reason and len(reason) > 100:
                        raise ValueError("'reason' too large (max 100 characters)")

                body = {
                        "broadcaster_user_id": broadcaster_user_id,
                        "duration": duration,
                        "reason": reason,
                        "user_id": user_id,
                }
                return await self._build_result(
                        "POST",
                        Endpoints.API.MODERATION_BANS,
                        {},
                        OAuthType.USER,
                        [OAuthScope.MODERATION_BAN],
                        api.PostModerationBanResponse,
                        body_json=body,
                        get_from_data=False,
                )

        async def delete_moderation_ban(
                self,
                user_id: int,
                broadcaster_user_id: int,
        ) -> api.DeleteModerationBanResponse:
                """Unban or remove timeout that was placed on the specific user.

                For detailed documentation, see here: https://docs.kick.com/apis/moderation#delete-moderation-bans

                Args:
                    user_id (int): User ID of the user that will be unbanned or removed the timeout.
                    broadcaster_user_id (int): Broadcaster User ID of the broadcaster's chat room.\n
                        **Dev note: At the moment, the API only supports the linked to the actual token.**
                """
                body = {"broadcaster_user_id": broadcaster_user_id, "user_id": user_id}
                return await self._build_result(
                        "DELETE",
                        Endpoints.API.MODERATION_BANS,
                        {},
                        OAuthType.USER,
                        [OAuthScope.MODERATION_BAN],
                        api.DeleteModerationBanResponse,
                        body_json=body,
                        get_from_data=False,
                )

        async def get_livestreams(
                self,
                broadcaster_user_id: int | list[int] | None = None,
                category_id: int | None = None,
                language: str | None = None,
                limit: int | None = None,
                sort: Literal["viewer_count", "started_at"] | None = None,
        ) -> Sequence[api.LiveStream]:
                """Get Livestreams based on `broadcaster_user_id`, `category_id`, `language`, `limit`, and `sort`.

                For detailed documentation, see here: https://docs.kick.com/apis/livestreams#get-livestreams

                Args:
                    broadcaster_user_id (int | list[int] | None, optional): Broadcaster User IDs. Defaults to `None`.
                    category_id (int | None, optional): Category ID. Defaults to `None`.
                    language (str | None, optional): Language of the livestream. Defaults to `None`.
                    limit (int | None, optional): Limit the number of results. Defaults to `None`.
                    sort (Literal[&quot;viewer_count&quot;, &quot;started_at&quot;] | None, optional): Sort by `viewer_count`
                        or `started_at`. Defaults to `None`.

                Raises:
                    ValueError: `broadcaster_user_id` must be max 50 entries.
                    ValueError: `limit` must be between 1 and 100.
                """
                _user_id = [broadcaster_user_id] if isinstance(broadcaster_user_id, int) else broadcaster_user_id
                if _user_id and len(_user_id) > 50:
                        raise ValueError("'broadcaster_user_id' must be max 50 entries")

                if limit and not (0 < limit < 101):
                        raise ValueError("'limit' must be between 1 and 100")

                params = {
                        "broadcaster_user_id": _user_id,
                        "category_id": category_id,
                        "language": language,
                        "limit": limit,
                        "sort": sort,
                }
                return await self._build_result(
                        "GET",
                        Endpoints.API.LIVESTREAMS,
                        params,
                        OAuthType.EITHER,
                        [],
                        list[api.LiveStream],
                        split_lists=True,
                )

        async def get_livestream_stats(self) -> api.LiveStreamStats | None:
                """Get Livestreams Stats.

                For detailed documentation, see here: https://docs.kick.com/apis/livestreams#get-livestreams-stats
                """
                return await self._build_result(
                        "GET",
                        Endpoints.API.LIVESTREAMS_STATS,
                        {},
                        OAuthType.USER,
                        [],
                        api.LiveStreamStats,
                )

        async def get_public_key(self) -> str:
                """Retrieve the public key used for verifying signatures.

                For detailed documentation, see here: https://docs.kick.com/apis/public-key#get-public-key
                """
                response = await self._build_result("GET", Endpoints.API.PUBLIC_KEY, {}, OAuthType.NONE, [], api.PublicKey)
                return response.public_key

        async def get_events_subscriptions(
                self,
                *,
                force_app_auth: bool = False,
        ) -> Sequence[api.EventSubscription]:
                """Get events subscriptions.

                For detailed documentation, see here: https://docs.kick.com/events/subscribe-to-events#get-events-subscriptions

                Args:
                    force_app_auth (bool): If true, app auth will be used. Otherwise, user auth will be used if available.
                        Defaults to `False`.
                """
                return await self._build_result(
                        "GET",
                        Endpoints.API.EVENTS_SUBSCRIPTIONS,
                        {},
                        OAuthType.EITHER if not force_app_auth else OAuthType.APP,
                        [OAuthScope.EVENTS_SUBSCRIBE],
                        list[api.EventSubscription],
                )

        async def post_events_subscriptions(
                self,
                events: list[WebhookEvents],
                broadcaster_user_id: int | None = None,
                method: Literal["webhook"] = "webhook",
                *,
                force_app_auth: bool = False,
        ) -> Sequence[api.PostEventSubscriptionResponse]:
                """Subscribe to events via webhooks.

                For detailed documentation, see here: https://docs.kick.com/events/subscribe-to-events#post-events-subscriptions

                ## Note:
                    **If user authentication is set, Kick API will override `broadcaster_user_id` with the
                    one linked to the user token. If you want to subscribe to multiple broadcasters, you should set
                    `force_app_auth` to `True`.**

                Args:
                    events (list[WebhookEvents]): List of events to subscribe.
                    broadcaster_user_id (int | None, optional): Broadcaster User ID. Defaults to `None`.
                    method (Literal[&quot;webhook&quot;]): Possible values: `webhook`. Defaults to `webhook`.
                    force_app_auth (bool): If true, app auth will be used. Otherwise, user auth will be used if available.
                        Defaults to `False`.
                """
                body = {
                        "broadcaster_user_id": broadcaster_user_id,
                        "events": [{"name": event.value.name, "version": event.value.version} for event in events],
                        "method": method,
                }
                return await self._build_result(
                        "POST",
                        Endpoints.API.EVENTS_SUBSCRIPTIONS,
                        {},
                        OAuthType.EITHER if not force_app_auth else OAuthType.APP,
                        [OAuthScope.EVENTS_SUBSCRIBE],
                        list[api.PostEventSubscriptionResponse],
                        body_json=body,
                )

        async def delete_events_subscriptions(
                self,
                event_id: list[str],
                *,
                force_app_auth: bool = False,
        ) -> bool:
                """Delete events subscriptions.

                For detailed documentation, see here: https://docs.kick.com/events/subscribe-to-events#delete-events-subscriptions

                ## Note:
                    **If user authentication is set, Kick API will override `broadcaster_user_id` with the
                    one linked to the user token. If you want to unsubscribe from multiple broadcasters, you should set
                    `force_app_auth` to `True`.**

                Args:
                    event_id (list[str]): Event Subscription IDs.
                    force_app_auth (bool): If true, app auth will be used. Otherwise, user auth will be used if available.
                        Defaults to `False`.

                Raises:
                    ValueError: `event_id` can't be an empty list.
                """
                if not len(event_id):
                        raise ValueError("event_id can't be an empty list")
                params = {"id": event_id}
                return (
                        await self._build_result(
                                "DELETE",
                                Endpoints.API.EVENTS_SUBSCRIPTIONS,
                                params,
                                OAuthType.EITHER if not force_app_auth else OAuthType.APP,
                                [OAuthScope.EVENTS_SUBSCRIBE],
                                None,
                                split_lists=True,
                                result_type=ResultType.STATUS_CODE,
                        )
                        == 204
                )
