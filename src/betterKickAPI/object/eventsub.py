# ruff: noqa: TC003, TC001
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AliasChoices, Field, dataclasses

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
        is_anonymous: Literal[True]
        user_id: None
        username: None
        is_verified: None
        profile_picture: None
        channel_slug: None
        identity: None


@dataclasses.dataclass
class UserInfo(KickObject):
        is_anonymous: Literal[False]
        user_id: int
        username: str
        is_verified: bool | None
        profile_picture: str
        channel_slug: str
        identity: Identity | None


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
        category: Category | None = Field(..., validation_alias=AliasChoices("category", "Category"))
        # HACK: apparently Kick API mistakenly sends it titled instead of lower case


@dataclasses.dataclass
class BannedMetadata(KickObject):
        reason: str
        created_at: datetime
        expires_at: datetime | None
