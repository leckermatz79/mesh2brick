# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""The conversation loop of the LLM layer, driven by a scripted Claude."""

from __future__ import annotations

from typing import Any

import pytest
from tests.llm_fakes import ScriptedClaude, answer, message, tool_call

from mesh2brick.agent.client import (
    Budget,
    LlmError,
    Prices,
    Request,
    Tool,
    Usage,
    anthropic_sender,
    converse,
    prices_for,
)

SCHEMA = {"type": "object", "properties": {}, "additionalProperties": False}


def echo_tool(calls: list[dict[str, Any]]) -> Tool:
    def run(data: dict[str, Any]) -> str:
        calls.append(data)
        if data.get("fail"):
            msg = "this input is not allowed"
            raise ValueError(msg)
        return f"echo {data}"

    return Tool(
        name="echo",
        description="Echo the input.",
        input_schema={"type": "object", "properties": {}},
        run=run,
    )


def request(*tools: Tool) -> Request:
    return Request(
        model="claude-sonnet-5-5", effort="medium", system="sys", tools=tools
    )


def budget(limit: float = 1.0) -> Budget:
    return Budget(prices=prices_for("claude-sonnet-5-5"), limit_usd=limit)


def needs_ok(data: Any) -> list[str]:
    return [] if data.get("ok") else ["ok must be true"]


def test_tool_calls_run_and_the_answer_is_accepted() -> None:
    calls: list[dict[str, Any]] = []
    claude = ScriptedClaude(tool_call("echo", {"x": 1}), answer({"ok": True}))
    exchange = converse(
        claude,
        request(echo_tool(calls)),
        [{"type": "text", "text": "go"}],
        schema=SCHEMA,
        validate=needs_ok,
        budget=budget(),
    )
    assert exchange.accepted
    assert exchange.answer == {"ok": True}
    assert exchange.turns == 2
    assert exchange.tool_calls == ("echo",)
    assert calls == [{"x": 1}]
    first, second = claude.requests
    assert first["tools"][0]["strict"] is True
    assert first["output_config"]["format"]["schema"] == SCHEMA
    assert first["output_config"]["effort"] == "medium"
    assert first["cache_control"] == {"type": "ephemeral"}
    assert "thinking" not in first  # adaptive by default; disabling is a 400
    result = second["messages"][-1]["content"][0]
    assert result["type"] == "tool_result"
    assert result["content"] == "echo {'x': 1}"
    assert exchange.usage == Usage(requests=2, input_tokens=200, output_tokens=40)


def test_tool_errors_and_unknown_tools_go_back_to_claude() -> None:
    calls: list[dict[str, Any]] = []
    claude = ScriptedClaude(
        tool_call("echo", {"fail": True}),
        tool_call("nope", {}),
        answer({"ok": True}),
    )
    converse(
        claude,
        request(echo_tool(calls)),
        [],
        schema=SCHEMA,
        validate=needs_ok,
        budget=budget(),
    )
    failed = claude.requests[1]["messages"][-1]["content"][0]
    unknown = claude.requests[2]["messages"][-1]["content"][0]
    assert failed["is_error"] is True
    assert "not allowed" in failed["content"]
    assert unknown["is_error"] is True
    assert "unknown tool" in unknown["content"]


def test_problems_go_back_once_then_the_last_answer_is_returned() -> None:
    claude = ScriptedClaude(answer({"ok": False}), answer({"ok": False, "n": 2}))
    exchange = converse(
        claude, request(), [], schema=SCHEMA, validate=needs_ok, budget=budget()
    )
    assert not exchange.accepted
    assert exchange.answer == {"ok": False, "n": 2}
    assert exchange.problems == ("ok must be true",)
    fix = claude.requests[1]["messages"][-1]["content"][0]["text"]
    assert "- ok must be true" in fix


def test_a_fixed_answer_is_accepted() -> None:
    claude = ScriptedClaude(answer({"ok": False}), answer({"ok": True}))
    exchange = converse(
        claude, request(), [], schema=SCHEMA, validate=needs_ok, budget=budget()
    )
    assert exchange.accepted


@pytest.mark.parametrize(
    ("reply", "problem"),
    [
        (message(stop="refusal"), "declined"),
        (message({"type": "text", "text": "{"}, stop="max_tokens"), "cut off"),
        (message({"type": "text", "text": "not json"}), "not valid JSON"),
    ],
)
def test_refusals_cut_offs_and_broken_json_fall_back(reply: Any, problem: str) -> None:
    exchange = converse(
        ScriptedClaude(reply, reply),
        request(),
        [],
        schema=SCHEMA,
        validate=needs_ok,
        budget=budget(),
    )
    assert not exchange.accepted
    assert problem in " ".join(exchange.problems)


def test_turn_and_cost_limits_stop_the_conversation() -> None:
    loop = [tool_call("echo", {}) for _ in range(5)]
    exchange = converse(
        ScriptedClaude(*loop),
        request(echo_tool([])),
        [],
        schema=SCHEMA,
        validate=needs_ok,
        budget=budget(),
        max_turns=3,
    )
    assert exchange.turns == 3
    assert "turn limit reached" in exchange.problems
    tight = budget(limit=0.0001)
    exchange = converse(
        ScriptedClaude(*loop),
        request(echo_tool([])),
        [],
        schema=SCHEMA,
        validate=needs_ok,
        budget=tight,
    )
    assert exchange.problems == ("cost limit reached",)
    assert exchange.turns == 1
    assert tight.exhausted


def test_cost_counts_every_kind_of_token() -> None:
    prices = Prices(input=2.0, output=10.0, cache_write=2.5, cache_read=0.2)
    usage = Usage(
        requests=1,
        input_tokens=1_000_000,
        output_tokens=100_000,
        cache_write_tokens=400_000,
        cache_read_tokens=1_000_000,
    )
    assert prices.cost(usage) == pytest.approx(2.0 + 1.0 + 1.0 + 0.2)
    assert prices_for("claude-sonnet-5-5") is not None
    assert prices_for("some-future-model") is None
    unknown = Budget(prices=None, limit_usd=0.0)
    unknown.charge(usage)
    assert unknown.cost_usd is None
    assert not unknown.exhausted
    assert (usage + usage).as_dict()["cache_read_tokens"] == 2_000_000


def test_real_sender_needs_the_llm_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins  # noqa: PLC0415

    real_import = builtins.__import__

    def no_anthropic(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "anthropic":
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_anthropic)
    with pytest.raises(LlmError, match="llm' extra") as caught:
        anthropic_sender()
    assert caught.value.fatal
