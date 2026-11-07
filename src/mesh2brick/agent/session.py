# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""One run of the LLM layer: tasks in order, a shared cost limit, a report.

The pipeline drives a :class:`LlmSession` like this::

    session = LlmSession(settings, placement.model, send=..., render=...)
    grouping = session.group_steps()
    placement = backend.merge_steps(placement, grouping.merges)
    session.use(placement.model)
    session.write_step_texts()
    model = session.annotate(placement.model)
    report = session.finish(model, store)

Every task falls back on its own: an API error, a refusal, the cost limit or
an answer that fails mesh2brick's checks leave that task's part of the
result as it is without the LLM layer, and the report says why. A fatal
error (rejected key, unknown model) skips the remaining tasks.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Literal

from mesh2brick.agent import prompts, tasks
from mesh2brick.agent.client import (
    Budget,
    LlmError,
    Request,
    Usage,
    converse,
    prices_for,
    text_block,
)
from mesh2brick.agent.describe import describe_model
from mesh2brick.agent.feedback import RunRecord
from mesh2brick.agent.tools import ToolContext, tools_for
from mesh2brick.steps.balance import largest_step
from mesh2brick.steps.regroup import new_step_index

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from mesh2brick.agent.client import Exchange, Sender
    from mesh2brick.agent.feedback import FeedbackStore
    from mesh2brick.config import Settings
    from mesh2brick.model import BrickModel

Status = Literal["accepted", "partial", "fallback", "skipped"]


@dataclass(frozen=True, slots=True)
class TaskReport:
    """How one task went.

    Attributes:
        task: ``group_steps``, ``write_step_text`` or ``choose_part``.
        status: ``accepted`` (whole answer used), ``partial`` (some proposals
            left out), ``fallback`` (nothing used) or ``skipped`` (not run).
        detail: one line for people, e.g. ``2 merges, 5 sections``.
        problems: what mesh2brick rejected, or why the task failed.
    """

    task: str
    status: Status
    detail: str
    usage: Usage = field(default_factory=Usage)
    turns: int = 0
    problems: tuple[str, ...] = ()
    tool_calls: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        """Plain data for the JSON report."""
        return {
            "task": self.task,
            "status": self.status,
            "detail": self.detail,
            "usage": self.usage.as_dict(),
            "turns": self.turns,
            "problems": list(self.problems),
            "tool_calls": list(self.tool_calls),
        }


@dataclass(frozen=True, slots=True)
class LlmReport:
    """What the LLM layer did in one run, and what it cost."""

    model: str
    effort: str
    tasks: tuple[TaskReport, ...]
    usage: Usage
    cost_usd: float | None
    seconds: float
    run_id: int | None = None
    outputs: dict[str, Any] = field(default_factory=dict)
    """What mesh2brick accepted, per task (1-based step numbers)."""

    def as_dict(self) -> dict[str, Any]:
        """Plain data for ``<name>.llm.json`` and the feedback store."""
        return {
            "model": self.model,
            "effort": self.effort,
            "cost_usd": None if self.cost_usd is None else round(self.cost_usd, 4),
            "seconds": round(self.seconds, 1),
            "usage": self.usage.as_dict(),
            "run_id": self.run_id,
            "tasks": [task.as_dict() for task in self.tasks],
            "outputs": self.outputs,
        }

    def summary(self) -> str:
        """One line for the console."""
        done = "; ".join(f"{t.task}: {t.detail}" for t in self.tasks)
        tokens = self.usage.input_tokens + self.usage.cache_read_tokens
        tokens += self.usage.cache_write_tokens + self.usage.output_tokens
        cost = "cost unknown" if self.cost_usd is None else f"${self.cost_usd:.3f}"
        return f"{done} ({tokens:,} tokens, {cost}, {self.seconds:.0f} s)"


class LlmSession:
    """The LLM layer's work on one model (see the module docstring)."""

    def __init__(
        self,
        settings: Settings,
        model: BrickModel,
        *,
        send: Sender,
        render: Callable[[BrickModel, int], bytes],
        picture: Callable[[BrickModel], bytes],
        source: str = "",
        examples: Callable[[str], list[str]] | None = None,
        notes: Sequence[str] = (),
    ) -> None:
        """Prepare a run on ``model``.

        ``render`` draws the model after a 0-based step, ``picture`` the
        finished model; ``examples`` returns example lines for a task from
        the feedback store, ``notes`` are the builder's recent feedback.
        """
        llm = settings.llm
        self.settings = settings
        self.send = send
        self.source = source
        self.started = time.monotonic()
        self.budget = Budget(prices=prices_for(llm.model), limit_usd=llm.max_cost_usd)
        self.context = ToolContext(
            model=model,
            language=settings.output.language,
            max_step_parts=largest_step(settings.steps.parts_per_step),
            render=render,
        )
        self.request = Request(
            model=llm.model,
            effort=llm.effort,
            system=prompts.SYSTEM,
            tools=tools_for(self.context),
        )
        self.picture = picture
        self._examples = examples or (lambda _task: [])
        self.notes = tuple(notes)
        self.reports: list[TaskReport] = []
        self.inputs = describe_model(model, settings.output.language)
        self.outputs: dict[str, Any] = {}
        self.sections: dict[int, str] = {}
        self.texts: dict[int, str] = {}
        self.stopped: str | None = None
        self.notes_for_user: list[str] = []
        if self.budget.prices is None:
            self.notes_for_user.append(
                f"mesh2brick does not know the prices of {llm.model}; the cost limit "
                "llm.max_cost_usd cannot be enforced"
            )

    def wants(self, task: str) -> bool:
        """Whether ``task`` is enabled in ``llm.tasks``."""
        return task in self.settings.llm.tasks

    # ------------------------------------------------------------------- tasks
    def group_steps(self) -> tasks.Grouping:
        """Ask for merges and sections; return what passed the checks."""
        name = "group_steps"
        if not self.wants(name) or not self._may_run(name):
            return tasks.Grouping()
        context = self.context
        prompt = [
            self._model_block(),
            *tasks.grouping_prompt(
                context,
                self.picture(context.model),
                self._examples(name),
                self.notes,
            ),
        ]
        exchange = self._converse(
            name,
            prompt,
            tasks.GROUPING_SCHEMA,
            lambda answer: tasks.check_grouping(context, answer),
        )
        if exchange is None:
            return tasks.Grouping()
        grouping = tasks.read_grouping(context, exchange.answer)
        used = bool(grouping.merges or grouping.sections)
        detail = f"{len(grouping.merges)} merge(s), {len(grouping.sections)} section(s)"
        self._report(name, exchange, used=used, detail=detail)
        mapping = new_step_index(grouping.merges, context.model.step_count)
        self.sections = {mapping[s]: title for s, title in grouping.sections.items()}
        self.outputs[name] = {
            "merges": [[a + 1, b + 1] for a, b in grouping.merges],
            "sections": {str(s + 1): t for s, t in grouping.sections.items()},
        }
        return grouping

    def use(self, model: BrickModel) -> None:
        """Continue on ``model`` (the model after applying the merges)."""
        self.context.use(model)

    def write_step_texts(self) -> dict[int, str]:
        """Ask for a text per step (in chunks); return the accepted texts."""
        name = "write_step_text"
        if not self.wants(name) or not self._may_run(name):
            return {}
        context = self.context
        texts: dict[int, str] = {}
        problems: list[str] = []
        usage, turns, calls = Usage(), 0, list[str]()
        model_block = self._model_block()
        for chunk in tasks.text_chunks(context.model):
            if not self._may_run(name, report=False):
                problems.append(self.stopped or "stopped")
                break
            prompt = [
                model_block,
                *tasks.texts_prompt(context, chunk, self._examples(name), self.notes),
            ]
            exchange = self._converse(
                name,
                prompt,
                tasks.TEXTS_SCHEMA,
                _text_checker(context, chunk),
                report=False,
            )
            if exchange is None:
                problems.append(self.stopped or "API error")
                break
            accepted, rejected = tasks.read_texts(context.model, chunk, exchange.answer)
            texts.update(accepted)
            problems.extend(rejected)
            problems.extend(p for p in exchange.problems if p not in rejected)
            usage, turns = usage + exchange.usage, turns + exchange.turns
            calls.extend(exchange.tool_calls)
        steps = context.model.step_count
        status: Status = (
            "accepted" if len(texts) == steps else "partial" if texts else "fallback"
        )
        self.reports.append(
            TaskReport(
                task=name,
                status=status,
                detail=f"{len(texts)} of {steps} step texts",
                usage=usage,
                turns=turns,
                problems=tuple(problems),
                tool_calls=tuple(calls),
            )
        )
        self.texts = texts
        self.outputs[name] = {str(s + 1): t for s, t in sorted(texts.items())}
        return texts

    def choose_parts(self, questions: Sequence[tasks.PartQuestion]) -> dict[int, int]:
        """Ask which option replaces each part; return item -> option (0-based)."""
        name = "choose_part"
        if not self.wants(name) or not questions or not self._may_run(name):
            return {}
        exchange = self._converse(
            name,
            tasks.choices_prompt(questions, self.context.language),
            tasks.CHOICES_SCHEMA,
            lambda answer: tasks.check_choices(questions, answer),
        )
        if exchange is None:
            return {}
        chosen, _ = tasks.read_choices(questions, exchange.answer)
        self._report(
            name,
            exchange,
            used=bool(chosen),
            detail=f"{len(chosen)} of {len(questions)} replacement(s) chosen",
        )
        self.outputs[name] = {
            questions[i].label: questions[i].options[o] for i, o in chosen.items()
        }
        return chosen

    # ------------------------------------------------------------------- result
    def annotate(self, model: BrickModel) -> BrickModel:
        """``model`` with the accepted section titles and step texts."""
        steps = tuple(
            replace(
                step,
                section=self.sections.get(index, step.section),
                text=self.texts.get(index, step.text),
            )
            for index, step in enumerate(model.steps)
        )
        return replace(model, steps=steps)

    def finish(self, model: BrickModel, store: FeedbackStore | None) -> LlmReport:
        """The run's report; recorded in ``store`` when given."""
        llm = self.settings.llm
        report = LlmReport(
            model=llm.model,
            effort=llm.effort,
            tasks=tuple(self.reports),
            usage=self.budget.usage,
            cost_usd=self.budget.cost_usd,
            seconds=time.monotonic() - self.started,
            outputs=self.outputs,
        )
        if store is None or not self.budget.usage.requests:
            return report
        run_id = store.record_run(
            RunRecord(
                name=model.name,
                source=self.source,
                language=self.settings.output.language,
                llm_model=llm.model,
                parts=model.part_count,
                steps=model.step_count,
                cost_usd=report.cost_usd,
                report=report.as_dict(),
                inputs=self.inputs,
                outputs=self.outputs,
                examples=_examples_of(model, self.sections, self.texts),
            )
        )
        return replace(report, run_id=run_id)

    # ------------------------------------------------------------------- helpers
    def _model_block(self) -> dict[str, Any]:
        """The model description (with accepted sections), a cache breakpoint."""
        model = self.annotate(self.context.model)
        block = text_block(describe_model(model, self.settings.output.language))
        block["cache_control"] = {"type": "ephemeral"}
        return block

    def _may_run(self, task: str, *, report: bool = True) -> bool:
        if self.stopped is None and self.budget.exhausted:
            self.stopped = "cost limit llm.max_cost_usd reached"
        if self.stopped is None:
            return True
        if report:
            self.reports.append(
                TaskReport(task=task, status="skipped", detail=self.stopped)
            )
        return False

    def _converse(
        self,
        task: str,
        prompt: list[dict[str, Any]],
        schema: dict[str, Any],
        validate: Callable[[Any], Sequence[str]],
        *,
        report: bool = True,
    ) -> Exchange | None:
        try:
            return converse(
                self.send,
                self.request,
                prompt,
                schema=schema,
                validate=validate,
                budget=self.budget,
                max_turns=self.settings.llm.max_turns,
            )
        except LlmError as error:
            if error.fatal:
                self.stopped = str(error)
            if report:
                self.reports.append(
                    TaskReport(
                        task=task, status="fallback", detail=str(error), problems=()
                    )
                )
            return None

    def _report(
        self, task: str, exchange: Exchange, *, used: bool, detail: str
    ) -> None:
        status: Status = (
            "accepted" if exchange.accepted else "partial" if used else "fallback"
        )
        self.reports.append(
            TaskReport(
                task=task,
                status=status,
                detail=detail,
                usage=exchange.usage,
                turns=exchange.turns,
                problems=exchange.problems,
                tool_calls=exchange.tool_calls,
            )
        )


def _text_checker(
    context: ToolContext, chunk: tasks.Range
) -> Callable[[Any], Sequence[str]]:
    def check(answer: Any) -> Sequence[str]:
        return tasks.check_texts(context, chunk, answer)

    return check


def _examples_of(
    model: BrickModel, sections: Mapping[int, str], texts: Mapping[int, str]
) -> dict[str, list[str]]:
    """Example lines later prompts may show if this run gets rated well."""
    examples: dict[str, list[str]] = {}
    if sections:
        examples["group_steps"] = [tasks.grouping_example(model)]
    if texts:
        chosen = sorted(texts)[:: max(1, len(texts) // 6)][:6]
        examples["write_step_text"] = [tasks.text_example(model, s) for s in chosen]
    return examples
