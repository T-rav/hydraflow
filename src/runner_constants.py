"""Shared constants for runner prompt templates."""

from __future__ import annotations

# The memory suggestion block is included verbatim in all runner and
# conflict-resolution prompts.  Each caller uses
# `MEMORY_SUGGESTION_PROMPT.format(context=...)` with its own context value:
# "implementation", "planning", "review", "correction", "conflict resolution",
# "rebuild", "shaping conversation", or "discovery run". Interpolating the
# constant unformatted leaks a literal "{context}" to the model — caught by
# test_no_prompt_leaks_an_unformatted_placeholder (ADR-0116).
MEMORY_SUGGESTION_PROMPT = """\
## Optional: Tribal-Knowledge Suggestion

If this {context} surfaced tribal knowledge that is ALL of durable (true a year
out), non-obvious (a senior engineer wouldn't get it from the code), load-bearing
(ignoring it breaks something or wastes real time), and general (a subsystem or
pattern, not one issue) — and not already obvious from CLAUDE.md or the code —
emit ONE block at the very end of your response:

MEMORY_SUGGESTION_START
principle: <the durable rule, one sentence>
rationale: <why — historical incident, design constraint, or hard-won lesson>
failure_mode: <what concretely breaks if this is ignored>
scope: <subsystem path, file glob, or "all">
MEMORY_SUGGESTION_END

Do not include issue/PR numbers, commit hashes, or dates in any field (they
rot). All four fields are required and non-trivial or the block is silently
dropped. Not for routine observations, refactor notes, or code-review nitpicks.
When in doubt, omit — the bar is "would I tell a new hire this on day one," and
most {context} runs should correctly produce no block.
"""

ADR_DRAFT_SUGGESTION_PROMPT = """\
If you believe this work reveals an architectural decision that should be
captured as an ADR, emit a block in this exact format at the end of your
transcript:

ADR_DRAFT_SUGGESTION:
title: <short title>
context: <paragraph or two>
decision: <the decision>
consequences: <consequences>
evidence:
  - issue: <github_issue_number>
  - issue: <github_issue_number>
  - wiki_entry: <ulid>

Only emit this if the pattern has been observed in ≥2 distinct issues and
feels load-bearing. The librarian will gate it further before opening an
ADR-draft issue.
"""
