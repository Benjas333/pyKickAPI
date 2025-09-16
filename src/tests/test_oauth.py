# ruff: noqa: ANN201
import os
from pathlib import PurePath

import pytest

from kick_api.kick import Kick
from kick_api.oauth import UserAuthenticationStorageHelper
from kick_api.types import OAuthScope

SCOPES = [
        OAuthScope.CHANNEL_READ,
        OAuthScope.CHANNEL_WRITE,
        OAuthScope.CHAT_WRITE,
        OAuthScope.EVENTS_SUBSCRIBE,
        OAuthScope.MODERATION_BAN,
        OAuthScope.USER_READ,
]


@pytest.mark.asyncio
async def test_oauth(kick_api: Kick):
        creds_file = PurePath("src/tests/oauth/user_token.json")
        authenticator = UserAuthenticationStorageHelper(kick_api, SCOPES, creds_file)
        await authenticator.bind()
        if not os.path.exists(creds_file):
                pytest.fail(f"Credentials file was not created ({creds_file})")
        assert kick_api.user_auth_token is not None
        user = await kick_api.get_users()
        assert len(user) > 0
        channel = await kick_api.get_channels()
        assert len(channel) > 0
