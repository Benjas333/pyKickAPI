from __future__ import annotations

from enum import Enum, auto
from typing import Callable

from pydantic import dataclasses, field_validator

__all__ = ["KICK_API_BASE_URL", "KICK_AUTH_BASE_URL", "Endpoints", "_Endpoint"]

KICK_API_BASE_URL = "https://api.kick.com/public/v1"
KICK_AUTH_BASE_URL = "https://id.kick.com"


@dataclasses.dataclass
class _Endpoint:
        base_url: str
        suffix: str

        @field_validator("base_url", mode="after")
        @classmethod
        def validate_base_url(cls, v: str) -> str:
                return v.removesuffix("/")

        @property
        def url(self) -> str:
                return self.base_url + self.suffix


class _API:
        CATEGORIES = _Endpoint(base_url=KICK_API_BASE_URL, suffix="/categories")
        category: Callable[[str | int], _Endpoint] = lambda category_id: _Endpoint(
                base_url=KICK_API_BASE_URL,
                suffix=f"{Endpoints.API.CATEGORIES.suffix}/{category_id}",
        )
        TOKEN_INTROSPECT = _Endpoint(base_url=KICK_API_BASE_URL, suffix="/token/introspect")
        USERS = _Endpoint(base_url=KICK_API_BASE_URL, suffix="/users")
        CHANNELS = _Endpoint(base_url=KICK_API_BASE_URL, suffix="/channels")
        CHAT_MESSAGE = _Endpoint(base_url=KICK_API_BASE_URL, suffix="/chat")
        MODERATION_BANS = _Endpoint(base_url=KICK_API_BASE_URL, suffix="/moderation/bans")
        LIVESTREAMS = _Endpoint(base_url=KICK_API_BASE_URL, suffix="/livestreams")
        LIVESTREAMS_STATS = _Endpoint(base_url=KICK_API_BASE_URL, suffix="/livestreams/stats")
        PUBLIC_KEY = _Endpoint(base_url=KICK_API_BASE_URL, suffix="/public-key")
        EVENTS_SUBSCRIPTIONS = _Endpoint(base_url=KICK_API_BASE_URL, suffix="/events/subscriptions")
        KICKS_LEADERBOARD = _Endpoint(base_url=KICK_API_BASE_URL, suffix="/kicks/leaderboard")


class _Auth:
        AUTHORIZATION = _Endpoint(base_url=KICK_AUTH_BASE_URL, suffix="/oauth/authorize")
        TOKEN = _Endpoint(base_url=KICK_AUTH_BASE_URL, suffix="/oauth/token")
        REVOKE_TOKEN = _Endpoint(base_url=KICK_AUTH_BASE_URL, suffix="/oauth/revoke")


class Endpoints:
        API = _API
        Auth = _Auth


class ResultType(Enum):
        RETURN_TYPE = auto()
        STATUS_CODE = auto()
        TEXT = auto()


class ServerStatus(Enum):
        CLOSED = auto()
        CLOSING = auto()
        OPENING = auto()
        OPENED = auto()
