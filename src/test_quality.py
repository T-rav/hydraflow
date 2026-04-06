"""Test Quality skill — checks branch diff for test quality issues.

Portable across Claude, Codex, and Pi backends. The skill is a pure prompt
executed by whichever agent CLI is configured; structured markers in the
transcript are parsed to determine pass/fail.
"""

from __future__ import annotations

import re


def build_test_quality_prompt(
    *, issue_number: int, issue_title: str, diff: str, **_kwargs: object
) -> str:
    """Build a prompt that asks an agent to review test quality in a diff."""
    return f"""You are running the Test Quality skill for issue #{issue_number}: {issue_title}.

Review the git diff below and assess the quality of test code changes.

## Diff

```diff
{diff}
```

## Checks

1. **Test naming convention** — test functions should follow `test_<unit>_<scenario>` pattern
2. **Duplicate test helpers** — new helpers that duplicate existing ones in the test suite (HIGH PRIORITY)
3. **Factory/builder patterns** — complex object construction should use factories, not inline construction
4. **Test isolation** — tests should not depend on execution order or shared mutable state
5. **Assertion quality** — tests should have specific assertions, not just `assert result` or `assert True`

## Instructions

- Only flag issues visible in the diff. Do not flag pre-existing problems.
- Focus on the HIGH PRIORITY anti-pattern: duplicate test helpers.
- Do NOT modify any files. This is a read-only assessment.

## Required Output

If quality is acceptable:
TEST_QUALITY_RESULT: OK
SUMMARY: Test quality is acceptable

If issues found:
TEST_QUALITY_RESULT: RETRY
SUMMARY: <comma-separated list of issue categories>
ISSUES:
- <file:function — description of issue>
"""


def parse_test_quality_result(transcript: str) -> tuple[bool, str, list[str]]:
    """Parse the structured output from a test quality transcript.

    Returns ``(passed, summary, issues)``.
    """
    status_match = re.search(
        r"TEST_QUALITY_RESULT:\s*(OK|RETRY)", transcript, re.IGNORECASE
    )
    if not status_match:
        return True, "No explicit result marker", []

    passed = status_match.group(1).upper() == "OK"
    summary_match = re.search(r"SUMMARY:\s*(.+)", transcript, re.IGNORECASE)
    summary = summary_match.group(1).strip() if summary_match else ""

    issues: list[str] = []
    issues_match = re.search(
        r"ISSUES:\s*\n((?:\s*-\s*.+\n?)+)", transcript, re.IGNORECASE
    )
    if issues_match:
        for line in issues_match.group(1).splitlines():
            stripped = line.strip().lstrip("- ").strip()
            if stripped:
                issues.append(stripped)

    return passed, summary, issues
