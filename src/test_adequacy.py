"""Test Adequacy skill — verifies changed code has sufficient test coverage.

Portable across Claude, Codex, and Pi backends. The skill is a pure prompt
executed by whichever agent CLI is configured; structured markers in the
transcript are parsed to determine pass/fail.
"""

from __future__ import annotations

import re


def build_test_adequacy_prompt(
    *, issue_number: int, issue_title: str, diff: str, **_kwargs: object
) -> str:
    """Build a prompt that asks an agent to assess test coverage of a diff."""
    return f"""You are running the Test Adequacy skill for issue #{issue_number}: {issue_title}.

Review the git diff below and assess whether the changed production code has adequate test coverage.

## Diff

```diff
{diff}
```

## Checks

For each changed or added production function/method/class, verify:

1. **Has a corresponding test** — at least one test exercises the new/changed path
2. **Edge cases covered** — empty inputs, None values, boundary conditions, error paths
3. **Regression safety** — if existing behavior changed, tests verify the new behavior
4. **No test-only gaps** — new test utilities or fixtures are themselves tested if non-trivial

## Instructions

- List each gap found with the production file:function and what test is missing.
- If coverage is adequate, report OK.
- Do NOT modify any files. This is a read-only assessment.
- Ignore test file changes when assessing adequacy — focus on whether production code is tested.

## Required Output

If coverage is adequate:
TEST_ADEQUACY_RESULT: OK
SUMMARY: All changed code has adequate test coverage

If gaps exist:
TEST_ADEQUACY_RESULT: RETRY
SUMMARY: <comma-separated list of gap categories>
GAPS:
- <production_file:function — what test is missing>
"""


def parse_test_adequacy_result(transcript: str) -> tuple[bool, str, list[str]]:
    """Parse the structured output from a test adequacy transcript.

    Returns ``(passed, summary, gaps)``.
    """
    status_match = re.search(
        r"TEST_ADEQUACY_RESULT:\s*(OK|RETRY)", transcript, re.IGNORECASE
    )
    if not status_match:
        return True, "No explicit result marker", []

    passed = status_match.group(1).upper() == "OK"
    summary_match = re.search(r"SUMMARY:\s*(.+)", transcript, re.IGNORECASE)
    summary = summary_match.group(1).strip() if summary_match else ""

    gaps: list[str] = []
    gaps_match = re.search(r"GAPS:\s*\n((?:\s*-\s*.+\n?)+)", transcript, re.IGNORECASE)
    if gaps_match:
        for line in gaps_match.group(1).splitlines():
            stripped = line.strip().lstrip("- ").strip()
            if stripped:
                gaps.append(stripped)

    return passed, summary, gaps


#: Human-readable labels for the repair prompt's verdict-source line.
_VERDICT_SOURCE_LABELS: dict[str, str] = {
    "llm-fail": "test-adequacy finder (LLM review of the diff)",
    "verifier-override": "independent test-adequacy verifier (second opinion)",
    "coverage-delta": (
        "deterministic coverage delta — changed production lines the test "
        "suite does not execute"
    ),
}

#: Cap findings injected into the repair prompt; the coverage delta can name
#: hundreds of lines and the repair pass only needs the concrete list, not
#: an unbounded prompt.
_MAX_REPAIR_FINDINGS = 30


def build_test_adequacy_repair_prompt(
    *,
    issue_number: int,
    issue_title: str,
    verdict_source: str,
    summary: str,
    findings: list[str],
    pass_number: int,
    max_passes: int,
    **_kwargs: object,
) -> str:
    """Build the bounded in-run repair prompt (#11593 seam 1).

    Handed to the SAME implementer worktree when the adequacy gate fails,
    instead of discarding the whole run: the concrete findings (finder gaps,
    verifier gaps, or coverage-delta uncovered lines) come back as a focused
    "write exactly these missing tests" instruction. The full check —
    including the independent verifier and the deterministic coverage delta —
    re-runs afterwards, so this pass can rescue the run but never weaken the
    gate.
    """
    source_label = _VERDICT_SOURCE_LABELS.get(verdict_source, verdict_source)
    shown = findings[:_MAX_REPAIR_FINDINGS]
    findings_block = "\n".join(f"- {f}" for f in shown) or "- (see summary above)"
    if len(findings) > _MAX_REPAIR_FINDINGS:
        findings_block += f"\n- (+ {len(findings) - _MAX_REPAIR_FINDINGS} more)"
    return f"""You are running a bounded Test Adequacy REPAIR pass ({pass_number} of {max_passes}) for issue #{issue_number}: {issue_title}.

The post-implementation test-adequacy gate REJECTED the current branch. This pass is your one chance to fix it in-run — write exactly the missing tests below instead of losing the whole attempt.

## Rejection

Source: {source_label}
Summary: {summary}

## Findings to fix

{findings_block}

## Instructions

- Write EXACTLY the tests these findings name — nothing more. No production-code rewrites, no refactoring, no scope creep.
- For coverage findings of the form `path:line`, add tests that execute those changed lines.
- Each new test must fail if the production change it covers were reverted or broken — tautological tests do not count.
- Do NOT delete or weaken production code or existing tests to make findings disappear.
- Run the tests you add and make them pass.
- Commit your work when done.

The full adequacy check (including the independent verifier and the deterministic coverage delta) re-runs after this pass; the final verdict is the re-checked one, not this pass's claim.
"""


def finder_asserted_adequate(transcript: str) -> bool:
    """Return ``True`` only when the finder emitted an explicit ``OK`` marker.

    This is the independent-verifier trigger predicate (#9546). It is
    deliberately stricter than :func:`parse_test_adequacy_result`: a
    transcript with **no** marker default-passes the finder (fail-soft for
    empty/garbled transcripts) but must **not** trigger the verifier —
    otherwise every scenario and fake-LLM path that relies on the no-marker
    default-pass would grow an unexpected second dispatch.
    """
    return (
        re.search(r"TEST_ADEQUACY_RESULT:\s*OK", transcript, re.IGNORECASE) is not None
    )


def build_test_adequacy_verifier_prompt(
    *, issue_number: int, issue_title: str, diff: str, **_kwargs: object
) -> str:
    """Build the independent second-opinion prompt for the verifier pass.

    The verifier is framed as an independent reviewer: it never sees the
    finder's verdict (so it cannot rubber-stamp it) and is instructed to
    default to OVERRIDE when it cannot positively confirm coverage.
    """
    return f"""You are the INDEPENDENT Test Adequacy Verifier for issue #{issue_number}: {issue_title}.

A prior automated pass assessed the test coverage of this diff. You have NOT been
shown its verdict, and you must not assume it was correct. Re-derive the adequacy
judgment yourself, from the diff alone.

## Diff

```diff
{diff}
```

## Instructions

- For each changed or added production function/method/class, independently confirm
  that at least one non-tautological test exercises the new/changed behaviour
  (a test that would fail if the production change were reverted or broken).
- Check edge cases: empty inputs, None values, boundary conditions, error paths.
- Ignore test-file changes when assessing adequacy — focus on whether production
  code is tested.
- Do NOT modify any files. This is a read-only assessment.
- If you cannot positively confirm that each changed production symbol is exercised
  by a meaningful test, you MUST report OVERRIDE. When unsure, OVERRIDE.

## Required Output

If you independently confirm coverage is adequate:
TEST_ADEQUACY_VERIFIER_RESULT: CONCUR
SUMMARY: <one-line justification>

If coverage is not confirmed adequate:
TEST_ADEQUACY_VERIFIER_RESULT: OVERRIDE
SUMMARY: <comma-separated list of gap categories>
GAPS:
- <production_file:function — what test is missing>
"""


def parse_test_adequacy_verifier_result(
    transcript: str,
) -> tuple[bool, str, list[str]]:
    """Parse the verifier transcript into ``(confirmed, summary, gaps)``.

    ``CONCUR`` → confirmed=True; ``OVERRIDE`` → confirmed=False. A missing
    marker returns confirmed=True (fail-soft, mirroring
    :func:`parse_test_adequacy_result`'s default-pass) — the caller applies
    the ``fail_closed`` policy for degraded verifier runs.
    """
    status_match = re.search(
        r"TEST_ADEQUACY_VERIFIER_RESULT:\s*(CONCUR|OVERRIDE)",
        transcript,
        re.IGNORECASE,
    )
    if not status_match:
        return True, "No explicit verifier result marker", []

    confirmed = status_match.group(1).upper() == "CONCUR"
    summary_match = re.search(r"SUMMARY:\s*(.+)", transcript, re.IGNORECASE)
    summary = summary_match.group(1).strip() if summary_match else ""

    gaps: list[str] = []
    gaps_match = re.search(r"GAPS:\s*\n((?:\s*-\s*.+\n?)+)", transcript, re.IGNORECASE)
    if gaps_match:
        for line in gaps_match.group(1).splitlines():
            stripped = line.strip().lstrip("- ").strip()
            if stripped:
                gaps.append(stripped)

    return confirmed, summary, gaps
