# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Talking to Claude: one tool-use conversation per task, usage and cost.

Only :func:`anthropic_sender` touches the network (``anthropic`` SDK, extra
``llm``); everything else works on a :data:`Sender`, so tests drive the
conversation with scripted responses.

A conversation (:func:`converse`) sends the task, runs the tools Claude
asks for, and reads the final answer, which structured outputs constrain to
a JSON schema. A validator then checks the answer against the model; if it
finds problems, Claude gets them back once to fix them. The caller always
receives the last answer and the problems that remain, so it can keep the
valid parts and fall back to the deterministic result for the rest (ADR
0013).
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, Literal

from mesh2brick.agent import prompts

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from anthropic.types import Message

    Sender = Callable[[dict[str, Any]], Message]
    """Sends one Messages API request (keyword arguments) and returns the reply."""

Effort = Literal["low", "medium", "high", "xhigh", "max"]
ToolOutput = str | list[dict[str, Any]]
MAX_TOKENS: Final = 32_000
"""Output ceiling per request (thinking included); requests are streamed."""


class LlmError(RuntimeError):
    """The API could not be used.

    ``fatal`` errors (rejected key, unknown model, network down) stop every
    remaining task of the run; others only the current task.
    """

    def __init__(self, message: str, *, fatal: bool = False) -> None:
        super().__init__(message)
        self.fatal = fatal


# ------------------------------------------------------------------- cost
@dataclass(frozen=True, slots=True)
class Usage:
    """Tokens used by one or more requests."""

    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            requests=self.requests + other.requests,
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
        )

    @classmethod
    def of(cls, message: Message) -> Usage:
        """Usage of one API reply."""
        usage = message.usage
        return cls(
            requests=1,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_write_tokens=usage.cache_creation_input_tokens or 0,
            cache_read_tokens=usage.cache_read_input_tokens or 0,
        )

    def as_dict(self) -> dict[str, int]:
        """Plain-data form for reports and the feedback store."""
        return {
            "requests": self.requests,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "cache_read_tokens": self.cache_read_tokens,
        }


@dataclass(frozen=True, slots=True)
class Prices:
    """US dollars per million tokens."""

    input: float
    output: float
    cache_write: float
    cache_read: float

    def cost(self, usage: Usage) -> float:
        """Price of ``usage`` in US dollars."""
        return (
            usage.input_tokens * self.input
            + usage.output_tokens * self.output
            + usage.cache_write_tokens * self.cache_write
            + usage.cache_read_tokens * self.cache_read
        ) / 1e6


PRICES: Final[dict[str, Prices]] = {
    # Anthropic list prices (standard tier, 5-minute cache writes) as of
    # 2026-11; reports keep the token counts, so costs can be recomputed.
    "claude-sonnet-5-5": Prices(2.0, 10.0, 2.5, 0.2),
    "claude-opus-5-5": Prices(4.0, 20.0, 5.0, 0.2),
    "claude-haiku-5-5": Prices(0.1, 0.5, 0.125, 0.01),
    "claude-fable-5-1": Prices(10.0, 50.0, 12.5, 0.25),
}


def prices_for(model: str) -> Prices | None:
    """List prices of ``model`` (``None``: not known to mesh2brick)."""
    return PRICES.get(model)


@dataclass(slots=True)
class Budget:
    """Running cost of one mesh2brick run against its limit.

    Mutable on purpose: the tasks of one run share it.
    """

    prices: Prices | None
    limit_usd: float
    usage: Usage = field(default_factory=Usage)

    @property
    def cost_usd(self) -> float | None:
        """Cost so far (``None``: unknown prices)."""
        return None if self.prices is None else self.prices.cost(self.usage)

    @property
    def exhausted(self) -> bool:
        """The cost limit is reached (never, for unknown prices)."""
        cost = self.cost_usd
        return cost is not None and cost >= self.limit_usd

    def charge(self, usage: Usage) -> None:
        """Add ``usage`` to the running total."""
        self.usage = self.usage + usage


# ------------------------------------------------------------------- tools
@dataclass(frozen=True, slots=True)
class Tool:
    """A tool Claude may call: definition plus the function behind it.

    ``run`` gets the (schema-valid) input and returns text or content blocks
    (text and images); a :class:`ValueError` becomes an error result that
    Claude can react to.
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    run: Callable[[dict[str, Any]], ToolOutput]

    def definition(self) -> dict[str, Any]:
        """The tool as the Messages API expects it (strict schema)."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "strict": True,
        }


def image_block(png: bytes) -> dict[str, Any]:
    """A PNG as an image content block."""
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": base64.standard_b64encode(png).decode("ascii"),
        },
    }


def text_block(text: str) -> dict[str, Any]:
    """Plain text as a content block."""
    return {"type": "text", "text": text}


# ------------------------------------------------------------------- conversation
@dataclass(frozen=True, slots=True)
class Request:
    """What stays the same for every request of a run (cacheable prefix)."""

    model: str
    effort: Effort
    system: str
    tools: tuple[Tool, ...]
    max_tokens: int = MAX_TOKENS


@dataclass(frozen=True, slots=True)
class Exchange:
    """Outcome of one conversation.

    Attributes:
        answer: the last JSON answer (``None``: none could be read).
        problems: what the validator still found in ``answer``, or why there
            is no answer; empty when the answer was accepted as a whole.
        usage: tokens of all requests of the conversation.
        turns: requests sent.
        tool_calls: names of the tools Claude called, in order.
    """

    answer: Any
    problems: tuple[str, ...]
    usage: Usage
    turns: int
    tool_calls: tuple[str, ...] = ()

    @property
    def accepted(self) -> bool:
        """An answer passed the validator without problems."""
        return self.answer is not None and not self.problems


def converse(
    send: Sender,
    request: Request,
    prompt: Sequence[dict[str, Any]],
    *,
    schema: dict[str, Any],
    validate: Callable[[Any], Sequence[str]],
    budget: Budget,
    max_turns: int = 8,
    max_fixes: int = 1,
) -> Exchange:
    """Run one task conversation until an answer is accepted or a limit hits.

    ``prompt`` is the first user message (content blocks). ``validate``
    returns the problems of a parsed answer (empty: accepted). Claude may
    call ``request.tools`` freely; at most ``max_fixes`` times it gets the
    validator's problems back to fix them.

    Raises:
        LlmError: if the API fails (see :class:`LlmError`).
    """
    messages: list[dict[str, Any]] = [{"role": "user", "content": list(prompt)}]
    tools = {tool.name: tool for tool in request.tools}
    usage = Usage()
    calls: list[str] = []
    answer: Any = None
    problems: tuple[str, ...] = ("no answer yet",)
    fixes = 0
    for turn in range(1, max_turns + 1):
        if budget.exhausted:
            return Exchange(
                answer, ("cost limit reached",), usage, turn - 1, tuple(calls)
            )
        reply = send(_params(request, messages, schema))
        step = Usage.of(reply)
        usage = usage + step
        budget.charge(step)
        if reply.stop_reason == "refusal":
            return Exchange(
                answer, ("Claude declined the task",), usage, turn, tuple(calls)
            )
        if reply.stop_reason == "max_tokens":
            stop = (f"the answer was cut off at {request.max_tokens} tokens",)
            return Exchange(answer, stop, usage, turn, tuple(calls))
        messages.append({"role": "assistant", "content": reply.content})
        uses = [block for block in reply.content if block.type == "tool_use"]
        if uses:
            calls.extend(block.name for block in uses)
            results = [
                _run_tool(tools, block.name, block.id, block.input) for block in uses
            ]
            messages.append({"role": "user", "content": results})
            continue
        if reply.stop_reason == "pause_turn":
            continue
        text = "".join(block.text for block in reply.content if block.type == "text")
        answer, problems = _read_answer(text, validate)
        if not problems or fixes >= max_fixes:
            return Exchange(answer, problems, usage, turn, tuple(calls))
        fixes += 1
        messages.append(
            {"role": "user", "content": [text_block(_fix_request(problems))]}
        )
    return Exchange(
        answer, (*problems, "turn limit reached"), usage, max_turns, tuple(calls)
    )


def _params(
    request: Request, messages: list[dict[str, Any]], schema: dict[str, Any]
) -> dict[str, Any]:
    return {
        "model": request.model,
        "max_tokens": request.max_tokens,
        "system": request.system,
        "messages": messages,
        "tools": [tool.definition() for tool in request.tools],
        "output_config": {
            "effort": request.effort,
            "format": {"type": "json_schema", "schema": schema},
        },
        # Automatic prompt caching: tools, system prompt and the growing
        # conversation are re-read from the cache on every later turn.
        "cache_control": {"type": "ephemeral"},
    }


def _run_tool(
    tools: dict[str, Tool], name: str, tool_use_id: str, data: object
) -> dict[str, Any]:
    tool = tools.get(name)
    result: dict[str, Any] = {"type": "tool_result", "tool_use_id": tool_use_id}
    if tool is None:
        return {**result, "content": f"unknown tool {name!r}", "is_error": True}
    if not isinstance(data, dict):
        return {**result, "content": "tool input must be an object", "is_error": True}
    try:
        return {**result, "content": tool.run(data)}
    except ValueError as error:
        return {**result, "content": str(error), "is_error": True}


def _read_answer(
    text: str, validate: Callable[[Any], Sequence[str]]
) -> tuple[Any, tuple[str, ...]]:
    try:
        answer = json.loads(text)
    except json.JSONDecodeError as error:
        return None, (f"the answer is not valid JSON ({error.msg})",)
    return answer, tuple(validate(answer))


def _fix_request(problems: Sequence[str]) -> str:
    return prompts.FIX.format(problems="\n".join(f"- {p}" for p in problems))


# ------------------------------------------------------------------- the real API
def anthropic_sender(*, timeout_s: float = 600.0) -> Sender:
    """A :data:`Sender` backed by the Anthropic API (extra ``llm``).

    Credentials come from the environment (``ANTHROPIC_API_KEY`` or an
    ``ant auth login`` profile). Requests are streamed, so long answers do
    not hit HTTP timeouts; the SDK retries rate limits and server errors.

    Raises:
        LlmError: (fatal) if the ``anthropic`` package is not installed; the
            sender raises it (fatal) for missing or rejected credentials.
    """
    try:
        import anthropic  # noqa: PLC0415 - optional extra
    except ImportError as error:
        msg = "the LLM layer needs the 'llm' extra: uv sync --extra llm"
        raise LlmError(msg, fatal=True) from error
    client = anthropic.Anthropic(timeout=timeout_s, max_retries=3)

    def send(params: dict[str, Any]) -> Message:
        try:
            with client.messages.stream(**params) as stream:
                return stream.get_final_message()
        except anthropic.AuthenticationError as error:
            raise LlmError(
                f"the API key was rejected: {error.message}", fatal=True
            ) from error
        except anthropic.PermissionDeniedError as error:
            raise LlmError(f"no permission: {error.message}", fatal=True) from error
        except anthropic.NotFoundError as error:
            msg = f"unknown model {params['model']!r}: {error.message}"
            raise LlmError(msg, fatal=True) from error
        except anthropic.BadRequestError as error:
            raise LlmError(f"request rejected: {error.message}", fatal=True) from error
        except anthropic.RateLimitError as error:
            raise LlmError(f"rate limited: {error.message}") from error
        except anthropic.APIStatusError as error:
            raise LlmError(f"API error {error.status_code}: {error.message}") from error
        except anthropic.APIConnectionError as error:
            raise LlmError(f"cannot reach the API: {error}", fatal=True) from error
        except TypeError as error:
            # The SDK finds no credentials only when it builds the request.
            if "authentication method" not in str(error):
                raise
            msg = "no API credentials: set ANTHROPIC_API_KEY (see README)"
            raise LlmError(msg, fatal=True) from error

    return send
