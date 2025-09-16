# ruff: noqa: TC003
from __future__ import annotations

from datetime import datetime

from pydantic import dataclasses, field_validator  # Field

from betterKickAPI.object.base import KickObject, KickObjectExtras  # AsyncIterKickObject,

__all__ = [
        "Category",
        "Channel",
        "DeleteModerationBanResponse",
        "EventSubscription",
        "LiveStream",
        "PostChatMessageResponse",
        "PostEventSubscriptionResponse",
        "PostModerationBanResponse",
        "PublicKey",
        "Stream",
        # 'GetCategoriesResponse',
        "TokenIntrospection",
        "User",
        "_Endpoint",
]


@dataclasses.dataclass
class Category(KickObject):
        id: int
        name: str
        thumbnail: str


# NOTE: Example for future endpoints that should use AsyncIterKickObject
# class GetCategoriesResponse(AsyncIterKickObject[Category]):
#         iterator: List[Category] = Field(alias='data', default_factory=list)
#         message: str


@dataclasses.dataclass
class TokenIntrospection(KickObject):
        active: bool = False
        client_id: str | None = None
        exp: datetime | None = None
        scope: str | None = None
        token_type: str | None = None


@dataclasses.dataclass
class User(KickObject):
        name: str
        profile_picture: str
        user_id: int
        email: str | None = None


@dataclasses.dataclass
class Stream(KickObject):
        is_live: bool
        is_mature: bool
        key: str
        language: str
        start_time: datetime
        thumbnail: str
        url: str
        viewer_count: int


@dataclasses.dataclass
class Channel(KickObject):
        banner_picture: str
        broadcaster_user_id: int
        channel_description: str
        slug: str
        stream_title: str
        category: Category | None = None
        stream: Stream | None = None

        @property
        def user_id(self) -> int:
                """`Channel.broadcaster_user_id` alias."""
                return self.broadcaster_user_id


@dataclasses.dataclass
class PostChatMessageResponse(KickObject):
        is_sent: bool
        message_id: str


@dataclasses.dataclass
class PostModerationBanResponse(KickObject):
        message: str
        data: dict | None = None


@dataclasses.dataclass
class DeleteModerationBanResponse(KickObject):
        message: str
        data: dict | None = None


@dataclasses.dataclass
class LiveStream(KickObject):
        broadcaster_user_id: int
        channel_id: int
        has_mature_content: bool
        language: str
        slug: str
        started_at: datetime
        stream_title: str
        thumbnail: str
        viewer_count: int
        category: Category | None = None


@dataclasses.dataclass
class LiveStreamStats(KickObjectExtras):  # XXX
        total_count: int


@dataclasses.dataclass
class PublicKey(KickObject):
        public_key: str


@dataclasses.dataclass
class EventSubscription(KickObject):
        app_id: str
        broadcaster_user_id: int
        created_at: datetime
        event: str
        id: str
        method: str
        updated_at: datetime
        version: int


@dataclasses.dataclass
class PostEventSubscriptionResponse(KickObject):
        name: str
        version: int
        error: str | None = None
        subscription_id: str | None = None


@dataclasses.dataclass
class _Endpoint(KickObject):
        base_url: str
        suffix: str

        @field_validator("base_url", mode="after")
        @classmethod
        def validate_base_url(cls, v: str) -> str:
                return v.removesuffix("/")

        @property
        def url(self) -> str:
                return self.base_url + self.suffix
