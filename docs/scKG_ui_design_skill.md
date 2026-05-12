---
name: scKG-ui-design
description: Use when designing or refactoring the scKG_Agent frontend. Applies evidence-first UI patterns for scientific tool recommendation, audit visibility, DOI/benchmark traceability, and conservative GPT/Gemini-style chat layouts.
---

# scKG UI Design

## Product Shape

Build a scientific recommendation workspace, not a marketing dashboard.

Preferred layout:

- left/sidebar: controls, mode, examples, safety status
- main: chat-style query and assistant report
- right or lower panels: recommended tools, evidence, missing evidence, audit state

## Must Show

Every recommendation UI should expose:

- recommended tool names
- score/rank only if produced by the backend
- publication or benchmark evidence when present
- missing evidence
- audit status
- caveats for weak benchmark support
- whether LLM calls are enabled or offline

## Must Avoid

Do not show:

- fake node counts
- fake edge counts
- fake growth deltas
- decorative gauges
- unsupported benchmark rankings
- "powered by" claims unrelated to configured runtime
- excessive emoji
- one-note blue/purple gradient themes

## Style

Use quiet, dense, professional UI:

- compact cards with small radius
- restrained neutral background
- clear labels and sections
- tables for evidence
- status chips for audit and missing evidence
- no nested cards
- no hero page

## Interaction

Default development mode should be offline-LLM safe.

If LLM is disabled, show it explicitly as a safety/cost state, not as an error.

Recommended controls:

- mode selector: offline structured / live agent
- explicit checkbox before paid LLM calls
- examples menu
- report download
- raw state expander for debugging

## Scientific Copy

Use conservative wording:

- "recommended by trusted evidence gate"
- "benchmark evidence available"
- "benchmark missing"
- "requires review"
- "exploratory"

Avoid strong claims unless the evidence bundle supports them.
