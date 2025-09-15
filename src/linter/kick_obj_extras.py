# ruff: noqa: E501
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pylint.checkers import BaseChecker
from pylint.checkers.utils import only_required_for_messages

if TYPE_CHECKING:
        from astroid import nodes
        from pylint.lint import PyLinter


def _node_name(node: nodes.NodeNG | None) -> Any:  # noqa: ANN401
        if node is None:
                return None
        name = getattr(node, "name", None)
        if isinstance(name, str):
                return name
        attr = getattr(node, "attrname", None)
        if isinstance(attr, str):
                return attr
        value = getattr(node, "value", None)
        if value is not None:
                return _node_name(value)
        return None


class KickObjectExtrasChecker(BaseChecker):
        name = "kickAPI-kick-obj-extras"

        msgs = {  # noqa: RUF012
                "W9001": (
                        "Use of 'KickObjectExtras' detected: change to 'KickObject' (reason: 'KickObjectExtras' is a place-holder class).",
                        "kick-obj-extras",
                        "Extended explanation: 'KickObjectExtras' is intended to be a place-holder class for unknown/uncertain API responses. It's recommended to use the main 'KickObject' class as soon as the API response is confirmed.",
                )
        }

        options = (
                (
                        "kick-obj-extras-allowed-modules",
                        {
                                "default": "",
                                "type": "string",
                                "metavar": "<modules>",
                                "help": "Comma separated array where KickObjectExtras is allowed (eg. tests.mock,experiments).",
                        },
                ),
        )

        def _is_allowed_module(self, node: nodes.NodeNG | None) -> bool:
                allowed = getattr(self.linter.config, "kick_obj_extras_allowed_modules", "") or ""
                allowed = [x.strip() for x in allowed.split(",") if x.strip()]
                if not allowed:
                        return False
                try:
                        mod = node.root().name if node is not None else None
                except Exception:  # noqa: BLE001
                        mod = None
                if mod:
                        for pattern in allowed:
                                if mod.startswith(pattern):
                                        return True
                return False

        def _report_if_name(self, node: nodes.NodeNG | None, target_name: str = "KickObjectExtras") -> None:
                if self._is_allowed_module(node):
                        return
                name = _node_name(node)
                if name == target_name:
                        self.add_message("W9001", node=node)

        @only_required_for_messages("kick-obj-extras")
        def visit_classdef(self, node: nodes.NodeNG | None) -> None:
                for base in getattr(node, "bases", ()):
                        self._report_if_name(base)


def register(linter: PyLinter) -> None:
        linter.register_checker(KickObjectExtrasChecker(linter))
