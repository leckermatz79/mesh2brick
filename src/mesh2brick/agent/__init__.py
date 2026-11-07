# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Optional LLM layer (extra ``llm``, Phase 7, ADR 0013).

Claude proposes, mesh2brick checks: merged steps and build sections
(:mod:`~mesh2brick.agent.tasks`, ``group_steps``), step texts
(``write_step_text``) and replacement parts (``choose_part``), each checked
against the model and the catalogue before it is used. The geometry
pipeline never depends on it.

* :mod:`~mesh2brick.agent.client`: conversations with Claude, usage, cost.
* :mod:`~mesh2brick.agent.tools`: what Claude may look up while it works.
* :mod:`~mesh2brick.agent.describe`, :mod:`~mesh2brick.agent.prompts`: the
  model in words and the prompt texts.
* :mod:`~mesh2brick.agent.session`: one run, with fallbacks and a report.
* :mod:`~mesh2brick.agent.feedback`: local ratings and few-shot examples.
"""
