from __future__ import annotations

import uuid
from enum import Enum
from typing import TYPE_CHECKING, Any, TypeVar
from urllib import parse

if TYPE_CHECKING:
        from collections.abc import AsyncGenerator

        from betterKickAPI.constants import _Endpoint
        from betterKickAPI.types import OAuthScope

T = TypeVar("T")

__all__ = [
        "build_scope",
        "build_url",
        "clean_url",
        "first",
        "limit",
]


def clean_url(url: str, default: _Endpoint) -> str:
        if url.removesuffix("/") == default.url:
                return default.url
        path = default.suffix.split("/")
        response = url
        for p in path[::-1]:
                response = url.removesuffix("/").removesuffix(p)
        return response.removesuffix("/") + default.suffix


def build_url(
        url: str,
        params: dict,
        *,
        remove_none: bool = False,
        split_lists: bool = False,
        enum_value: bool = True,
) -> str:
        def get_val(val: Any) -> str:  # noqa: ANN401
                if not enum_value:
                        return str(val)
                if isinstance(val, Enum):
                        return str(val.value)
                return str(val)

        def add_param(res: list, k: str, v: Any) -> None:  # noqa: ANN401
                res.append("&" if len(res) > 1 else "?")
                res.append(str(k))
                if v is None:
                        return
                res.append("=")
                res.append(parse.quote(get_val(v)))

        result = [url]
        for key, value in params.items():
                if value is None and remove_none:
                        continue

                if not (split_lists and isinstance(value, list)):
                        add_param(result, key, value)
                        continue

                for v in value:
                        add_param(result, key, v)
        return "".join(result)


def build_scope(scopes: list[OAuthScope]) -> str:
        return " ".join(scopes)


async def first(gen: AsyncGenerator[T, None]) -> T | None:
        try:
                return await gen.__anext__()
        except StopAsyncIteration:
                return None


async def limit(gen: AsyncGenerator[T, None], num: int) -> AsyncGenerator[T, None]:
        if num < 1:
                raise ValueError("num has to be int >= 1")
        c = 0
        async for y in gen:
                c += 1
                if c > num:
                        break
                yield y


def get_uuid() -> uuid.UUID:
        return uuid.uuid4()


# def done_task_callback(logger: Logger, task: asyncio.Future) -> None:
#         e = task.exception()
#         if e is None:
#                 return
#         logger.exception("Error while running callback: %s", e, exc_info=e)
