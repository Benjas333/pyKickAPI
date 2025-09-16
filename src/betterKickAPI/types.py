from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from enum_tools import document_enum
from strenum import StrEnum

__all__ = [
        "AlreadyConnectedError",
        "EventSubSubscriptionError",
        "InvalidRefreshTokenException",
        "InvalidTokenException",
        "KickAPIException",
        "KickAuthorizationException",
        "KickBackendException",
        "KickResourceNotFound",
        "MissingAppSecretException",
        "MissingScopeException",
        "OAuthScope",
        "OAuthType",
        "UnauthorizedException",
        "WebhookEvents",
]


@document_enum
class OAuthScope(StrEnum):
        """Enum of OAuth scopes"""

        USER_READ = "user:read"
        """View user information in Kick including username, streamer ID, etc."""
        CHANNEL_READ = "channel:read"
        """View channel information in Kick including channel description, category, etc."""
        CHANNEL_WRITE = "channel:write"
        """Update livestream metadata for a channel based on the channel ID"""
        CHAT_WRITE = "chat:write"
        """Send chat messages and allow chat bots to post in your chat"""
        STREAMKEY_READ = "streamkey:read"
        """Read a user's stream URL and stream key"""
        EVENTS_SUBSCRIBE = "events:subscribe"
        """Subscribe to all channel events on Kick e.g. chat messages, follows, subscriptions"""
        MODERATION_BAN = "moderation:ban"
        """Execute moderation actions for moderators"""


class OAuthType(Enum):
        NONE = auto()
        USER = auto()
        APP = auto()
        EITHER = auto()


@dataclass
class _WebhookEvent:
        name: str
        version: int


class WebhookEvents(Enum):
        # """Represents the possible events to listen for using `~kickAPI.webhook.Webhook.register_event()`."""

        # READY = _WebhookEvent(name="ready", version=1)
        # """Triggered when the bot is started up and ready."""
        CHAT_MESSAGE = _WebhookEvent(name="chat.message.sent", version=1)
        """Triggered when someone wrote a message in a chat channel."""
        CHANNEL_FOLLOW = _WebhookEvent(name="channel.followed", version=1)
        """Triggered when someone followed a channel."""
        CHANNEL_SUBSCRIPTION_RENEWAL = _WebhookEvent(name="channel.subscription.renewal", version=1)
        """Triggered when someone renewed its subscription to a channel."""
        CHANNEL_SUBSCRIPTION_GIFTS = _WebhookEvent(name="channel.subscription.gifts", version=1)
        """Triggered when someone gifted one or more subscriptions to a channel."""
        CHANNEL_SUBSCRIPTION_CREATED = _WebhookEvent(name="channel.subscription.new", version=1)
        """Triggered when someone subscribed to a channel."""
        LIVESTREAM_STATUS_UPDATED = _WebhookEvent(name="livestream.status.updated", version=1)
        """Triggered when the livestream status is updated."""
        LIVESTREAM_METADATA_UPDATED = _WebhookEvent(name="livestream.metadata.updated", version=1)
        """Triggered when the livestream metadata is updated."""
        MODERATION_BANNED = _WebhookEvent(name="moderation.banned", version=1)
        """Triggered when someone is banned by a moderator."""


class KickAPIException(Exception):
        pass


class InvalidRefreshTokenException(KickAPIException):
        pass


class InvalidTokenException(KickAPIException):
        pass


# class NotFoundException(KickAPIException):
#         pass


class KickAuthorizationException(KickAPIException):
        pass


class UnauthorizedException(KickAuthorizationException):
        pass


class MissingScopeException(KickAuthorizationException):
        pass


class KickBackendException(KickAPIException):
        pass


class MissingAppSecretException(KickAPIException):
        pass


# class EventSubSubscriptionTimeout(KickAPIException):
#         pass


# class EventSubSubscriptionConflict(KickAPIException):
#         pass


class EventSubSubscriptionError(KickAPIException):
        pass


# class DeprecatedError(KickAPIException):
#         pass


class KickResourceNotFound(KickAPIException):
        pass


# class ForbiddenError(KickAPIException):
#         pass


class AlreadyConnectedError(Exception):
        pass
