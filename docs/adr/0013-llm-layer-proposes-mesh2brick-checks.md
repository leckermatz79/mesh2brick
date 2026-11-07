# 13. LLM layer: Claude proposes, mesh2brick checks

- Status: accepted
- Date: 2026-11-07

## Context

SPEC Phase 7 asks for an optional LLM layer (Anthropic API) for judgement calls: step
grouping, sub-assemblies, step texts and part choice when it is ambiguous. Its output must
always be checked against the catalogue and stability, with the deterministic result as
fallback, and the cost of every run must be logged. A feedback store with ratings, few-shot
examples and an export for later fine-tuning is part of the phase.

What we found while building it:

- The geometry pipeline already decides parts, positions and a stability-checked order.
  An LLM cannot see cells; letting it reorder parts would need a second stability check
  per proposal and invites errors we cannot always detect.
- What builders miss in our booklets is not a different order but orientation: what a
  step is for, and which part of the model a group of steps builds.
- Part choice has one real ambiguity left: parts LEGO does not make in the model's colour
  when `parts.availability: report` keeps them (the default `exclude` avoids them).

## Decision

1. **Claude proposes, mesh2brick checks.** Every task has a JSON answer format
   (structured outputs) and a validator in `agent/tasks.py`. Claude gets the validator's
   problems back once to fix them; what still fails is dropped, item by item, and the
   result without the LLM layer stays. A refusal, an API error, the cost limit or a cut-off
   answer end only that task.
2. **The tasks are narrow on purpose:**
   - `group_steps` may only merge runs of consecutive steps. A merge never changes the
     order of parts, so the model after each new step equals the model after some old step:
     no part can hang, every stability verdict still holds. `merge_problems` refuses runs
     that mix sub-assemblies, contain an attach step, exceed `parts_per_step + 3` parts,
     hide a moment that needs a supporting hand, or cover earlier parts by more than half.
     The backend applies accepted merges to its own plan, so the `.mpd` follows. The task
     also names 2–12 build sections ("Sockel", "Kopf"), shown in the PDF.
   - `write_step_text` writes one sentence per step. Every part the text names as new
     must be placed in that step (with at most that quantity), and every number in it must
     be a quantity of that step (part sizes like `2 × 4` excepted).
   - `choose_part` (opt-in) picks among replacements mesh2brick computed from the
     catalogue: shorter parts of the same colour, or the same part in the nearest
     colours LEGO makes it in. It never changes the model, only the parts-list note.
3. **Tools:** `catalog_lookup`, `stability_check` (the very check that decides later)
   and `render_preview` (a step picture as in the booklet). All tools and one system
   prompt are sent with every request of a run, so the prompt cache covers them; the model
   description is a second cache breakpoint. Claude gets, per step, what the new parts sit
   on ("sits on sub-assembly A"), which made texts locate parts correctly.
4. **Model and settings:** `claude-sonnet-5-5` (SPEC default), effort `medium` (Anthropic's
   recommended start for multi-step tool use; texts were good at this level), adaptive
   thinking as the model's default, streamed requests, `llm.max_cost_usd: 1.0` per run.
   We do not send the server-side refusal fallback (`fallbacks`): on Sonnet 5.5 it only
   retries `cyber` and `frontier_llm` declines, which do not apply to building
   instructions, and our own fallback already covers every refusal at no cost.
5. **Feedback store:** SQLite in the user's data folder, nothing is uploaded. Runs rated
   4–5 supply example lines to later prompts of the same language; recent notes are passed
   on; `--export` writes JSON lines.

## Consequences

- With `llm.enabled: false` (default) nothing changes. With it, real models cost about
  $0.06–0.20 and 20–60 s (docs/benchmarks.md, Phase 7); the cost is logged in
  `<name>.llm.json` and the feedback store.
- Claude rarely merges steps: the deterministic pass already merged the small ones, and
  most remaining neighbours cover each other. Sections and texts carry the value.
- Step texts are only as good as the description; Claude does not see every step picture
  (it may ask for up to 12 per run). Wrong but plausible wording that passes the checks is
  possible; the feedback store is the way to correct the style over time.
- Prompts live in `agent/prompts.py`, the price table in `agent/client.py` (as of
  2026-11; unknown models run without an enforceable cost limit and say so).
