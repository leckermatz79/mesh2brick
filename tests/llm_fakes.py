# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""A scripted stand-in for the Anthropic API, for tests of the LLM layer."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

import pytest

if os.environ.get("MESH2BRICK_REQUIRE_LLM"):
    from anthropic.types import Message  # CI: a missing extra must fail, not skip
else:
    Message = pytest.importorskip(
        "anthropic.types", reason="needs the optional 'llm' extra"
    ).Message

Reply = Callable[[dict[str, Any]], Any]


def message(
    *blocks: dict[str, Any],
    stop: str = "end_turn",
    input_tokens: int = 100,
    output_tokens: int = 20,
    cache_read: int = 0,
) -> Any:
    """An API reply with the given content blocks (plain dicts)."""
    return Message.model_validate(
        {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-5-5",
            "content": list(blocks),
            "stop_reason": stop,
            "stop_sequence": None,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_input_tokens": cache_read,
            },
        }
    )


def answer(data: object, **usage: int) -> Any:
    """A final reply whose text is ``data`` as JSON."""
    return message({"type": "text", "text": json.dumps(data)}, **usage)


def tool_call(name: str, data: dict[str, Any], call_id: str = "toolu_1") -> Any:
    """A reply that calls one tool."""
    block = {"type": "tool_use", "id": call_id, "name": name, "input": data}
    return message(block, stop="tool_use")


class ScriptedClaude:
    """Answers requests from a script; records what it was sent.

    Each script entry is a reply, or a function of the request that returns
    one (to answer depending on the task).
    """

    def __init__(self, *script: Any) -> None:
        self.script = list(script)
        self.requests: list[dict[str, Any]] = []

    def __call__(self, params: dict[str, Any]) -> Any:
        self.requests.append(json.loads(json.dumps(params, default=_plain)))
        if not self.script:
            msg = "the scripted conversation ran out of replies"
            raise AssertionError(msg)
        reply = self.script.pop(0)
        return reply(params) if callable(reply) else reply

    def prompts(self) -> list[str]:
        """The text of every request's first user message."""
        return [
            " ".join(
                block.get("text", "")
                for block in request["messages"][0]["content"]
                if isinstance(block, dict)
            )
            for request in self.requests
        ]


def _plain(value: object) -> object:
    dump = getattr(value, "model_dump", None)
    return dump() if callable(dump) else str(value)
