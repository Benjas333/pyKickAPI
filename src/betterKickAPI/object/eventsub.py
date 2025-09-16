# ruff: noqa: TC003, TC001
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AliasChoices, AliasGenerator, ConfigDict, Field, dataclasses

from betterKickAPI.object.api import Category
from betterKickAPI.object.base import KickObject

__all__ = [
        "AnonUserInfo",
        "BannedMetadata",
        "Emote",
        "EmotePosition",
        "Identity",
        "IdentityBadge",
        "LivestreamMetadata",
        "RepliedMessage",
        "UserInfo",
        "WebhookVerificationHeaders",
]


@dataclasses.dataclass
class IdentityBadge(KickObject):
        text: str
        type: str
        count: int | None = None


@dataclasses.dataclass
class Identity(KickObject):
        username_color: str
        badges: list[IdentityBadge] = Field(default_factory=list)


@dataclasses.dataclass
class AnonUserInfo(KickObject):
        is_anonymous: Literal[True] = True
        user_id: None = None
        username: None = None
        is_verified: None = None
        profile_picture: None = None
        channel_slug: None = None
        identity: None = None


@dataclasses.dataclass
class UserInfo(KickObject):
        user_id: int
        username: str
        is_verified: bool
        profile_picture: str
        channel_slug: str
        is_anonymous: Literal[False] = False
        identity: Identity | None = None


@dataclasses.dataclass
class EmotePosition(KickObject):
        start: int = Field(..., alias="s")
        end: int = Field(..., alias="e")


@dataclasses.dataclass
class Emote(KickObject):
        emote_id: str
        positions: list[EmotePosition]


@dataclasses.dataclass
class RepliedMessage(KickObject):
        message_id: str
        content: str
        sender: UserInfo


@dataclasses.dataclass
class LivestreamMetadata(KickObject):
        title: str
        language: str
        has_mature_content: bool
        category: Category | None = None


@dataclasses.dataclass
class BannedMetadata(KickObject):
        created_at: datetime
        expires_at: datetime | None = None
        reason: str = ""


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
class WebhookVerificationHeaders(KickObject):
        kick_event_message_id: str | None = None
        kick_event_subscription_id: str | None = None
        kick_event_signature: str | None = None
        kick_event_message_timestamp: str | None = None
        kick_event_type: str | None = None
        kick_event_version: str | None = None

