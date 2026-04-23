"""Shape Coherence skill — evaluates a Shape proposal for rubric compliance.

See docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md
§4.10. Returns RETRY with one of five keywords:

- too-few-options            (fewer than 2 substantive options beyond do-nothing)
- missing-defer              (no explicit "defer / do nothing / status quo" option)
- options-overlap            (options share >50% of the code/scope surface)
- missing-tradeoffs          (at least one option lists no cost/risk)
- dropped-discover-question  (Discover-named open question not addressed)
"""

from __future__ import annotations

import re


def build_shape_coherence_prompt(
    *,
    issue_number: int,
    issue_title: str,
    discover_brief: str = "",
    proposal: str = "",
    **_kwargs: object,
) -> str:
    """Build a prompt that asks an agent to evaluate a Shape proposal.

    ``discover_brief`` is the upstream brief the proposal is responding to
    (may be empty if the issue skipped Discover — the rubric is still
    applicable except for criterion 5).
    ``proposal`` is the Shape proposal text to evaluate.
    """
    return f"""You are running the Shape Coherence skill for issue #{issue_number}: {issue_title}.

You are evaluating a SHAPE PROPOSAL against the five-criterion rubric
below. You are NOT producing a proposal — you are judging one.

## Upstream Discover Brief (for criterion 5)

```
{discover_brief}
```

## Shape Proposal To Evaluate

```
{proposal}
```

## Rubric — All Five Must Pass

1. **At least two substantive options beyond do-nothing.** The
   proposal must list ≥2 distinct product directions, each with a
   name and an approach. "Do nothing" / "defer" alone is not a
   substantive option; it is required separately (criterion 2). If
   fewer than two substantive options are present, emit RETRY
   keyword `too-few-options`.

2. **Do-nothing option present.** The proposal must explicitly
   include a "Defer", "No-op", "Accept status quo", or equivalent
   option, naming the cost of inaction. Missing → RETRY keyword
   `missing-defer`.

3. **Mutually exclusive scope.** Options must not overlap in the
   code areas or user surfaces they touch beyond a 50% threshold.
   Pairwise-compare each option's stated scope (affected files /
   modules / UI areas). If any pair overlaps >50% of the smaller
   option's surface, emit RETRY keyword `options-overlap`. Judgement
   call: if two options both say "edit src/foo.py and src/bar.py"
   but differ only in comment wording, that is overlap.

4. **Trade-offs named per option.** Every option lists at least ONE
   concrete cost, risk, or trade-off — not just upsides. "This is
   the best option" without a downside is a missing-tradeoffs
   failure. If any option lacks a named trade-off, emit RETRY
   keyword `missing-tradeoffs`.

5. **Reconciles Discover ambiguities.** If the upstream Discover
   brief's *Open questions* section named open questions, the Shape
   proposal must address each — either pick a position in one of
   the options, or explicitly punt with a rationale. Un-addressed
   questions → RETRY keyword `dropped-discover-question`. If the
   Discover brief is empty or lists no open questions, this
   criterion is automatically satisfied.

## Instructions

- Check criteria in order (1 → 5). Report every failure, but put the
  FIRST failing keyword in the SUMMARY line (the adversarial corpus
  asserts on it).
- For `dropped-discover-question`, emit one FINDINGS entry per
  un-addressed question (quote it from the Discover brief).
- Do NOT modify any files. This is a read-only evaluation.

## Required Output

If all five criteria pass:
SHAPE_COHERENCE_RESULT: OK
SUMMARY: All five rubric criteria pass

If any criterion fails:
SHAPE_COHERENCE_RESULT: RETRY
SUMMARY: <first-failing-keyword> — <short description>
FINDINGS:
- <keyword> — <specific evidence>
"""


_STATUS_RE = re.compile(r"SHAPE_COHERENCE_RESULT:\s*(OK|RETRY)", re.IGNORECASE)
_SUMMARY_RE = re.compile(r"SUMMARY:\s*(.+)", re.IGNORECASE)
_FINDINGS_RE = re.compile(r"FINDINGS:\s*\n((?:\s*-\s*.+\n?)+)", re.IGNORECASE)


def parse_shape_coherence_result(
    transcript: str,
) -> tuple[bool, str, list[str]]:
    """Parse the structured output from a shape-coherence transcript.

    Returns ``(passed, summary, findings)``. Fails open on a missing
    result marker, matching the sibling skills' posture.
    """
    status_match = _STATUS_RE.search(transcript)
    if not status_match:
        return True, "No explicit result marker", []

    passed = status_match.group(1).upper() == "OK"
    summary_match = _SUMMARY_RE.search(transcript)
    summary = summary_match.group(1).strip() if summary_match else ""

    findings: list[str] = []
    findings_match = _FINDINGS_RE.search(transcript)
    if findings_match:
        for line in findings_match.group(1).splitlines():
            stripped = line.strip().lstrip("- ").strip()
            if stripped:
                findings.append(stripped)

    return passed, summary, findings
