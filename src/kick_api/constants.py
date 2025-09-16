from __future__ import annotations

from enum import Enum, auto
from typing import Callable

from kick_api.object.api import _Endpoint

__all__ = ["KICK_API_BASE_URL", "KICK_AUTH_BASE_URL", "Endpoints"]

KICK_API_BASE_URL = "https://api.kick.com/public/v1"
KICK_AUTH_BASE_URL = "https://id.kick.com"


class _API:
        CATEGORIES = _Endpoint(base_url=KICK_API_BASE_URL, suffix="/categories")
        category: Callable[[str | int], _Endpoint] = (
                lambda category_id: _Endpoint(
                        base_url=KICK_API_BASE_URL,
                        suffix=f"{Endpoints.API.CATEGORIES.suffix}/{category_id}",
                )
        )
        TOKEN_INTROSPECT = _Endpoint(
                base_url=KICK_API_BASE_URL, suffix="/token/introspect"
        )
        USERS = _Endpoint(base_url=KICK_API_BASE_URL, suffix="/users")
        CHANNELS = _Endpoint(base_url=KICK_API_BASE_URL, suffix="/channels")
        CHAT_MESSAGE = _Endpoint(base_url=KICK_API_BASE_URL, suffix="/chat")
        MODERATION_BANS = _Endpoint(
                base_url=KICK_API_BASE_URL, suffix="/moderation/bans"
        )
        LIVESTREAMS = _Endpoint(base_url=KICK_API_BASE_URL, suffix="/livestreams")
        LIVESTREAMS_STATS = _Endpoint(base_url=KICK_API_BASE_URL, suffix="/livestreams/stats")
        PUBLIC_KEY = _Endpoint(base_url=KICK_API_BASE_URL, suffix="/public-key")
        EVENTS_SUBSCRIPTIONS = _Endpoint(
                base_url=KICK_API_BASE_URL, suffix="/events/subscriptions"
        )


class _Auth:
        AUTHORIZATION = _Endpoint(
                base_url=KICK_AUTH_BASE_URL, suffix="/oauth/authorize"
        )
        TOKEN = _Endpoint(base_url=KICK_AUTH_BASE_URL, suffix="/oauth/token")
        REVOKE_TOKEN = _Endpoint(base_url=KICK_AUTH_BASE_URL, suffix="/oauth/revoke")


class Endpoints:
        API = _API
        Auth = _Auth


class ResultType(Enum):
        RETURN_TYPE = auto()
        STATUS_CODE = auto()
        TEXT = auto()
