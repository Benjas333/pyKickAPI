from __future__ import annotations

from collections.abc import Generator
from logging import Filter, LogRecord, getLogger
from os import getenv
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio
from dotenv import load_dotenv

from kickAPI.kick import Kick

if TYPE_CHECKING:
        from collections.abc import AsyncGenerator, Generator

load_dotenv()
APP_ID, APP_SECRET = getenv("APP_ID", ""), getenv("APP_SECRET", "")
if not (APP_ID and APP_SECRET):
        raise RuntimeError("You must specify APP_ID and APP_SECRET env vars for testing")


class OnlyKickAPIFilter(Filter):
        def __init__(self, prefix: str) -> None:
                super().__init__()
                self.prefix = prefix

        def filter(self, record: LogRecord) -> bool | LogRecord:
                return record.name.startswith(self.prefix) or record.name == 'root'


@pytest.fixture(scope="session", autouse=True)
def logger() -> Generator[None, Any, None]:
        # handler = StreamHandler()
        # handler.addFilter(OnlyKickAPIFilter("kickAPI"))
        root = getLogger()
        # root.handlers = []
        for handler in root.handlers:
                handler.addFilter(OnlyKickAPIFilter("kickAPI"))
        # root.addHandler(handler)
        # root.setLevel(DEBUG)
        yield


@pytest_asyncio.fixture(scope="session")
async def kick_api() -> AsyncGenerator[Kick, None]:
        kick = await Kick(APP_ID, APP_SECRET)
        yield kick
        await kick.close()
