"""Discover Completeness skill — evaluates a Discover brief for rubric compliance.

Portable across Claude, Codex, and Pi backends. Pure prompt + parser;
structured markers in the transcript are parsed to determine pass/fail
and to extract the specific RETRY keyword the rubric names.

See docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md
§4.10 for the rubric. Returns RETRY with one of five keywords:

- missing-section:<name>  (structure failure)
- shallow-section:<name>  (non-trivial-content failure)
- paraphrase-only         (no new information vs. the issue body)
- vague-criterion         (acceptance criteria not testable)
- hid-ambiguity           (zero open questions despite ambiguous input)
"""

from __future__ import annotations

import re


def build_discover_completeness_prompt(
    *,
    issue_number: int,
    issue_title: str,
    issue_body: str = "",
    brief: str = "",
    **_kwargs: object,
) -> str:
    """Build a prompt that asks an agent to evaluate a Discover brief.

    ``issue_body`` is the original issue text the brief was produced from.
    ``brief`` is the discovery brief to evaluate. Both are required for a
    meaningful rubric check — the rubric compares the two.
    """
    return f"""You are running the Discover Completeness skill for issue #{issue_number}: {issue_title}.

You are evaluating a DISCOVERY BRIEF against the five-criterion rubric
below. You are NOT producing a brief — you are judging one.

## Original Issue Body

```
{issue_body}
```

## Discovery Brief To Evaluate

```
{brief}
```

## Rubric — All Five Must Pass

1. **Structure.** The brief MUST contain named sections for *Intent*,
   *Affected area*, *Acceptance criteria*, *Open questions*, and
   *Known unknowns*. Section headings may be any case, any heading
   style (`##`, `**bold**`, plain line ending in `:`); the keyword
   must appear. If any section is absent, emit RETRY keyword
   `missing-section:<name>` where `<name>` is the lower-kebab
   canonical section name (`intent`, `affected-area`,
   `acceptance-criteria`, `open-questions`, `known-unknowns`).

2. **Non-trivial content.** Each section has ≥50 characters of prose
   OR ≥3 bulleted items (bullets required for *Acceptance criteria*
   and *Open questions*). If a section is present but too short,
   emit RETRY keyword `shallow-section:<name>` (same canonical
   section names).

3. **No paraphrase-only.** At least one section adds information NOT
   present in the original issue body — e.g. names a competitor, a
   constraint, an affected file, a measurable target, a persona, or
   a sequenced sub-problem. A brief that only rephrases the issue
   body in different words is a paraphrase-only failure: emit RETRY
   keyword `paraphrase-only`.

4. **Concrete acceptance criteria.** Every bullet in *Acceptance
   criteria* names an observable outcome — a metric, a UI state, a
   CLI exit code, a parsed field, a benchmark threshold.  Vague
   aspirations ("the app is faster", "users are happier", "it feels
   better") fail. If any bullet is vague, emit RETRY keyword
   `vague-criterion`.

5. **Open questions when ambiguous.** If the issue body contains
   ambiguity markers — any of: "maybe", "could be", "not sure", "it
   depends", "we might", "possibly", "unclear", "tbd" — the brief's
   *Open questions* section MUST list at least one explicit
   question. A brief that claims zero open questions despite
   ambiguous input is hiding ambiguity: emit RETRY keyword
   `hid-ambiguity`.

## Instructions

- Check each criterion in order (1 → 5). A single brief may fail
  multiple criteria; report every failure, but put the FIRST failing
  keyword in the SUMMARY line (the adversarial corpus asserts on it).
- For `missing-section:<name>` and `shallow-section:<name>`, emit one
  FINDINGS entry per offending section (so a brief missing three
  sections produces three findings).
- Do NOT modify any files. This is a read-only evaluation.

## Required Output

If all five criteria pass:
DISCOVER_COMPLETENESS_RESULT: OK
SUMMARY: All five rubric criteria pass

If any criterion fails:
DISCOVER_COMPLETENESS_RESULT: RETRY
SUMMARY: <first-failing-keyword> — <short description>
FINDINGS:
- <keyword> — <specific evidence, quoting the brief or issue body>
"""


_STATUS_RE = re.compile(r"DISCOVER_COMPLETENESS_RESULT:\s*(OK|RETRY)", re.IGNORECASE)
_SUMMARY_RE = re.compile(r"SUMMARY:\s*(.+)", re.IGNORECASE)
_FINDINGS_RE = re.compile(r"FINDINGS:\s*\n((?:\s*-\s*.+\n?)+)", re.IGNORECASE)


def parse_discover_completeness_result(
    transcript: str,
) -> tuple[bool, str, list[str]]:
    """Parse the structured output from a discover-completeness transcript.

    Returns ``(passed, summary, findings)``. If no explicit result marker
    is present, returns ``(True, "No explicit result marker", [])`` —
    matching the other skill parsers' fail-open posture so a blank
    transcript does not block the pipeline.
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
