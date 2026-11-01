# 1. Record architecture decisions

- Status: accepted
- Date: 2026-11-01

## Context

mesh2brick is developed in "vibe-coding" mode: the product owner decides goals and taste,
the implementer (Claude Code) makes the technical decisions. Those decisions must stay
understandable later, by the product owner, new contributors and future sessions.

## Decision

Every architectural decision gets a short Architecture Decision Record (ADR) in `docs/adr/`,
numbered `NNNN-title.md`, following Michael Nygard's format (context, decision,
consequences). The decision itself is explained in 3–5 plain sentences that a non-expert can
follow. Superseded ADRs stay in place and are marked as superseded, with a link to the new one.

## Consequences

Decisions are traceable and can be challenged later. Writing an ADR costs a few minutes per
decision. Small, local implementation choices do not need one; they go into code comments or
the PR description.
