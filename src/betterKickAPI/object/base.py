# ruff: noqa: TC001
from __future__ import annotations

from collections.abc import Awaitable, Mapping
from json import JSONDecodeError
from typing import (
        Any,
        Callable,
        Generic,
        Literal,
        Self,
        TypeAlias,
        TypeVar,
        Union,
)

import httpx
import orjson as json
from pydantic import BaseModel, ConfigDict, Field, RootModel, dataclasses

from betterKickAPI import helper
from betterKickAPI.types import OAuthScope, OAuthType

T = TypeVar("T")

__all__ = ["AsyncIterData", "AsyncIterKickObject", "KickObject", "KickObjectExtras"]


# class KickObject(BaseModel):
#         model_config = ConfigDict(serialize_by_alias=True, validate_assignment=True)

#         @classmethod
#         def parse_optional_datetime(cls, val: Any) -> datetime | None:
#                 try:
#                         from dateutil import parser as du_parser
#                 except ImportError:
#                         du_parser = None
#                 parsed = None
#                 if val is None:
#                         parsed = None
#                 if isinstance(val, datetime):
#                         parsed = val
#                 if isinstance(val, (int, float)):
#                         parsed = datetime.fromtimestamp(val)
#                 if isinstance(val, str):
#                         try:
#                                 parsed = datetime.fromtimestamp(float(val))
#                         except ValueError:
#                                 pass
#                         if du_parser:
#                                 parsed = du_parser.isoparse(val) if len(val) else None
#                         parsed = datetime.fromisoformat(val) if len(val) else None
#                 return parsed

#         @classmethod
#         def parse_datetime(cls, val: Any) -> datetime:
#                 date = KickObject.parse_optional_datetime(val)
#                 if not date:
#                         raise ValueError(f"Not possible to parse {val=}")
#                 return date


IncEx: TypeAlias = Union[
        set[int],
        set[str],
        Mapping[int, Union["IncEx", bool]],
        Mapping[str, Union["IncEx", bool]],
]


@dataclasses.dataclass(config=ConfigDict(serialize_by_alias=True, validate_assignment=True))
class KickObject:
        def model_dump(
                self,
                *,
                mode: str | Literal["json", "python"] = "python",
                include: Any = None,  # noqa: ANN401
                exclude: Any = None,  # noqa: ANN401
                context: dict[str, Any] | None = None,
                by_alias: bool | None = None,
                exclude_unset: bool = False,
                exclude_defaults: bool = False,
                exclude_none: bool = False,
                round_trip: bool = False,
                warnings: bool | Literal["none", "warn", "error"] = True,
                serialize_as_any: bool = False,
        ) -> Any:  # noqa: ANN401
                """This method is included just to get a more accurate return type for type checkers.
                It is included in this `if TYPE_CHECKING:` block since no override is actually necessary.

                See the documentation of `BaseModel.model_dump` for more details about the arguments.

                Generally, this method will have a return type of `RootModelRootType`, assuming that `RootModelRootType` is
                not a `BaseModel` subclass. If `RootModelRootType` is a `BaseModel` subclass, then the return
                type will likely be `dict[str, Any]`, as `model_dump` calls are recursive. The return type could
                even be something different, in the case of a custom serializer.
                Thus, `Any` is used here to catch all of these cases.
                """
                return RootModel[type(self)](self).model_dump(
                        mode=mode,
                        include=include,
                        exclude=exclude,
                        context=context,
                        by_alias=by_alias,
                        exclude_unset=exclude_unset,
                        exclude_defaults=exclude_defaults,
                        exclude_none=exclude_none,
                        round_trip=round_trip,
                        warnings=warnings,
                        serialize_as_any=serialize_as_any,
                )

        def model_dump_json(
                self,
                *,
                indent: int | None = None,
                include: IncEx | None = None,
                exclude: IncEx | None = None,
                context: Any | None = None,  # noqa: ANN401
                by_alias: bool | None = None,
                exclude_unset: bool = False,
                exclude_defaults: bool = False,
                exclude_none: bool = False,
                round_trip: bool = False,
                warnings: bool | Literal["none", "warn", "error"] = True,
                fallback: Callable[[Any], Any] | None = None,
                serialize_as_any: bool = False,
        ) -> str:
                """!!! abstract "Usage Documentation"
                [`model_dump_json`](../concepts/serialization.md#modelmodel_dump_json)

                Generates a JSON representation of the model using Pydantic's `to_json` method.

                Args:
                        indent: Indentation to use in the JSON output. If None is passed, the output will be compact.
                        include: Field(s) to include in the JSON output.
                        exclude: Field(s) to exclude from the JSON output.
                        context: Additional context to pass to the serializer.
                        by_alias: Whether to serialize using field aliases.
                        exclude_unset: Whether to exclude fields that have not been explicitly set.
                        exclude_defaults: Whether to exclude fields that are set to their default value.
                        exclude_none: Whether to exclude fields that have a value of `None`.
                        round_trip: If True, dumped values should be valid as input for non-idempotent types such as Json[T].
                        warnings: How to handle serialization errors. False/"none" ignores them, True/"warn" logs errors,
                                "error" raises a [`PydanticSerializationError`][pydantic_core.PydanticSerializationError].
                        fallback: A function to call when an unknown value is encountered. If not provided,
                                a [`PydanticSerializationError`][pydantic_core.PydanticSerializationError] error is raised.
                        serialize_as_any: Whether to serialize fields with duck-typing serialization behavior.

                Returns:
                        A JSON string representation of the model.
                """
                return RootModel[type(self)](self).model_dump_json(
                        indent=indent,
                        include=include,
                        exclude=exclude,
                        context=context,
                        by_alias=by_alias,
                        exclude_unset=exclude_unset,
                        exclude_defaults=exclude_defaults,
                        exclude_none=exclude_none,
                        round_trip=round_trip,
                        warnings=warnings,
                        fallback=fallback,
                        serialize_as_any=serialize_as_any,
                )


@dataclasses.dataclass(config=ConfigDict(serialize_by_alias=True, validate_assignment=True, extra="allow"))
class KickObjectExtras(KickObject):
        """Class that handles extra fields for model_dump and model_dump_json.

        ## Warning: this is intended to be a place-holder class for unknown/uncertain API responses.
        ## It's recommended to use the main `KickObject` class as soon as the API response is confirmed.
        """

        def model_dump(
                self,
                *,
                mode: str | Literal["json"] | Literal["python"] = "python",
                include: Any = None,  # noqa: ANN401
                exclude: Any = None,  # noqa: ANN401
                context: dict[str, Any] | None = None,
                by_alias: bool | None = None,
                exclude_unset: bool = False,
                exclude_defaults: bool = False,
                exclude_none: bool = False,
                round_trip: bool = False,
                warnings: bool | Literal["none"] | Literal["warn"] | Literal["error"] = True,
                serialize_as_any: bool = False,
        ) -> Any:  # noqa: ANN401
                response = self.__dict__.copy()
                for key, field in self.__dataclass_fields__.items():
                        if not hasattr(field.default, "alias"):
                                continue
                        response.pop(key)

                response.update(
                        super().model_dump(
                                mode=mode,
                                include=include,
                                exclude=exclude,
                                context=context,
                                by_alias=by_alias,
                                exclude_unset=exclude_unset,
                                exclude_defaults=exclude_defaults,
                                exclude_none=exclude_none,
                                round_trip=round_trip,
                                warnings=warnings,
                                serialize_as_any=serialize_as_any,
                        )
                )
                return response

        def model_dump_json(
                self,
                *,
                indent: int | None = None,
                include: set[int]
                | set[str]
                | Mapping[int, set[int] | set[str] | Mapping[int, IncEx | bool] | Mapping[str, IncEx | bool] | bool]
                | Mapping[str, set[int] | set[str] | Mapping[int, IncEx | bool] | Mapping[str, IncEx | bool] | bool]
                | None = None,
                exclude: set[int]
                | set[str]
                | Mapping[int, set[int] | set[str] | Mapping[int, IncEx | bool] | Mapping[str, IncEx | bool] | bool]
                | Mapping[str, set[int] | set[str] | Mapping[int, IncEx | bool] | Mapping[str, IncEx | bool] | bool]
                | None = None,
                context: Any | None = None,  # noqa: ANN401
                by_alias: bool | None = None,
                exclude_unset: bool = False,
                exclude_defaults: bool = False,
                exclude_none: bool = False,
                round_trip: bool = False,
                warnings: bool | Literal["none"] | Literal["warn"] | Literal["error"] = True,
                fallback: Callable[[Any], Any] | None = None,
                serialize_as_any: bool = False,
        ) -> str:
                return json.dumps(
                        self.model_dump(
                                mode="json",
                                include=include,
                                exclude=exclude,
                                context=context,
                                by_alias=by_alias,
                                exclude_unset=exclude_unset,
                                exclude_defaults=exclude_defaults,
                                exclude_none=exclude_none,
                                round_trip=round_trip,
                                warnings=warnings,
                                serialize_as_any=serialize_as_any,
                        ),
                        fallback,
                        json.OPT_INDENT_2 if indent is not None and indent > 0 else None,
                ).decode()


class AsyncIterData(BaseModel):
        req: Callable[..., Awaitable[httpx.Response]]
        method: str
        url: str
        param: dict
        split: bool
        auth_t: OAuthType
        auth_s: list[OAuthScope]
        body: dict | None = None
        custom_headers: dict[str, str] | None = None
        in_data: bool


@dataclasses.dataclass
class AsyncIterKickObject(KickObject, Generic[T]):
        idx: int = Field(0, exclude=True)
        iter_data: AsyncIterData = Field(exclude=True)

        iterator: list[T] = Field(default_factory=list)

        # _item_type: type | None = Field(default_factory=lambda: PrivateAttr(None))
        # _adapter: TypeAdapter | None = Field(default_factory=lambda: PrivateAttr(None))

        # @model_validator(mode="after")
        # def define_item_type(self) -> Self:
        #         args = get_args(self.__annotations__["iterator"])
        #         if args:
        #                 self.item_type = args[0]
        #         elif len(self.iterator):
        #                 self.item_type = type(self.iterator[0])
        #         return self

        def __aiter__(self) -> Self:
                return self

        # @property
        # def item_type(self) -> type | None:
        #         return self._item_type

        # @item_type.setter
        # def item_type(self, value: type | None) -> None:
        #         if self._item_type is not None or value is None:
        #                 return
        #         self._item_type = value
        #         # try:
        #         #         self._adapter = TypeAdapter(list[self._item_type])
        #         # except Exception:
        #         #         self._adapter = None

        @property
        def current_page(self) -> int:
                return self.iter_data.param.get("page", 1)

        @property
        def iter_field(self) -> str:
                return ""

        async def __anext__(self) -> T:
                items = self.iterator
                if not isinstance(items, list):
                        raise ValueError("Missing iterator list field")

                if len(items) > self.idx:
                        self.idx += 1
                        return items[self.idx - 1]
                        # self.item_type = type(item)

                actual_page = self.iter_data.param.get("page", 1)
                self.iter_data.param["page"] = actual_page + 1
                # raise StopAsyncIteration()
                _url = helper.build_url(
                        self.iter_data.url,
                        self.iter_data.param,
                        remove_none=True,
                        split_lists=self.iter_data.split,
                )
                async with httpx.AsyncClient() as ses:
                        r = await self.iter_data.req(
                                self.iter_data.method,
                                ses,
                                _url,
                                self.iter_data.auth_t,
                                self.iter_data.auth_s,
                                data=self.iter_data.body,
                                custom_headers=self.iter_data.custom_headers,
                        )
                        try:
                                resp_data = json.loads(r.content)
                        except JSONDecodeError:
                                resp_data = {}
                        await r.aclose()

                if self.iter_data.in_data:
                        resp_data = resp_data.get("data", resp_data)

                incoming_items = resp_data.get(self.__dataclass_fields__["iterator"].default.alias, [])

                # validated_items = incoming_items
                # adapter = self._adapter
                # if adapter is not None:
                #         validated_items = adapter.validate_python(incoming_items)

                self.iterator = incoming_items  # type: ignore
                self.idx = 1
                if not len(self.iterator):
                        raise StopAsyncIteration()
                return self.iterator[self.idx - 1]
