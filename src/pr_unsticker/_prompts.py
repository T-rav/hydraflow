"""Every Claude-bound prompt the unsticker builds.

Both builders are registered targets in ``scripts/audit_prompts.py`` and
are scored against the ADR-0087 rubric, so they are graded together and
regress together — the same reason ``reviewer._prompts`` exists.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from prompt_stats import build_prompt_stats, truncate_with_notice

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from models import GitHubIssue


logger = logging.getLogger("hydraflow.pr_unsticker")


class PRUnstickerPromptMixin:
    """Every Claude-bound prompt the unsticker builds."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``PRUnsticker.__init__`` or by a sibling
    # mixin. The method declarations are TYPE_CHECKING-only on purpose: a
    # runtime ``...`` body is a real class attribute and would win the MRO
    # over the sibling that really implements it (#11629).
    # ------------------------------------------------------------------
    _config: HydraFlowConfig

    def _build_ci_fix_prompt(
        self, issue: GitHubIssue, pr_url: str, cause: str
    ) -> tuple[str, dict[str, object]]:
        """Build a targeted prompt for CI/quality fix and pruning stats."""
        cause_text, cause_before, cause_after = truncate_with_notice(
            cause or "",
            self._config.max_unsticker_cause_chars,
            label="Escalation reason",
        )
        prompt = f"""You are fixing CI/quality failures for a pull request.

## Issue: {issue.title}
Issue URL: {issue.url}
PR URL: {pr_url}

## Escalation Reason

{cause_text}

## Instructions

Plan before fixing. Run `make quality` to see failures, then read the
failing code and its context to understand the root cause. Check git log
to see if a recent merge introduced the problem. You can read any file
in the repo or use `gh` CLI for additional context.

Common causes after a merge-main: duplicate Pydantic Field definitions,
duplicate function parameters, or stale test assertions. grep for the
field or string name if you suspect duplicates.

Fix root causes — do NOT skip, disable, or weaken any tests or checks.
Run `make quality` again to verify. Before committing, review your own
diff — you may catch things `make quality` won't.

## Rules

- Follow the project's CLAUDE.md guidelines strictly.
- NEVER delete or overwrite existing CLAUDE.md content. You may append new sections or
  modify existing sections, but you must preserve all information already present.
- Write tests for all new code — tests are mandatory.
- Do NOT push to remote. Do NOT create pull requests.
- Do NOT run `git push` or `gh pr create`.
- Ensure `make quality` passes before committing.
"""
        stats = build_prompt_stats(
            history_before=cause_before,
            history_after=cause_after,
            section_chars={
                "cause_before": cause_before,
                "cause_after": cause_after,
            },
        )
        return prompt, stats

    def _build_ci_timeout_fix_prompt(
        self,
        issue: GitHubIssue,
        pr_url: str,
        cause: str,
        isolation_output: str,
        *,
        learned_patterns_section: str = "",
    ) -> tuple[str, dict[str, object]]:
        """Build a targeted prompt for fixing hanging tests."""
        cause_text, cause_before, cause_after = truncate_with_notice(
            cause or "",
            self._config.max_unsticker_cause_chars,
            label="Escalation reason",
        )
        isolation_text, iso_before, iso_after = truncate_with_notice(
            isolation_output or "",
            self._config.max_unsticker_cause_chars,
            label="Test isolation",
        )

        learned_block = (
            f"\n{learned_patterns_section}\n" if learned_patterns_section else ""
        )

        prompt = f"""You are fixing a CI timeout caused by hanging tests in a pull request.

## Issue: {issue.title}
Issue URL: {issue.url}
PR URL: {pr_url}

## Escalation Reason

{cause_text}

## Test Isolation Output

{isolation_text}

## Common Causes of Hanging Tests

**General (any language):**
- **Infinite polling loops**: Test mocks return a truthy "work available" value on every call, \
so a loop that skips sleep when work is done never yields. Fix: ensure mocks return "no work" \
(falsy/empty) by default.
- **Unresolved async waits**: Tests await on events, futures, promises, or channels that \
never complete. Fix: ensure the mock or test setup triggers the completion signal.
- **Deadlocks**: Multiple concurrent tasks/threads waiting on each other's locks or results.
- **Missing teardown**: Servers, listeners, or background threads started in tests that \
never get shut down, preventing the test process from exiting.

**Python-specific:**
- **Truthy AsyncMock**: `AsyncMock()` without `return_value` returns a truthy MagicMock, \
causing `while await work_fn()` or `did_work = bool(await fn())` loops to spin forever. \
Fix: set `return_value` to a falsy value matching the function's return type — \
`return_value=0` for int, `return_value=[]` for list, `return_value=False` for bool.
- **Missing event.set()**: Tests that wait on `asyncio.Event` objects that never get set.
{learned_block}
## Instructions

1. Identify which test is hanging from the test output above (the last test that started running).
2. Read the hanging test and the code it exercises.
3. Fix the **root cause** — do NOT mask the problem with timeouts or skip markers.
4. **Search the same file for other occurrences of the same pattern** (e.g., other mocks \
with the same issue). Fix ALL instances, not just the one that hangs — unfixed siblings \
will hang on the next CI run.
5. Run `make quality` to verify all tests pass and no new issues are introduced.
6. Commit fixes with a descriptive message.

## Pattern Reporting

If you identify a new hang pattern not already listed above, emit a structured block so it \
can be learned for future fixes:

```
TROUBLESHOOTING_PATTERN_START
pattern_name: <short_key, e.g. truthy_asyncmock>
description: <what causes the hang>
fix_strategy: <how to fix it>
TROUBLESHOOTING_PATTERN_END
```

## Rules

- Follow the project's CLAUDE.md guidelines strictly.
- NEVER delete or overwrite existing CLAUDE.md content. You may append new sections or
  modify existing sections, but you must preserve all information already present.
- Write tests for all new code — tests are mandatory.
- Do NOT push to remote. Do NOT create pull requests.
- Do NOT run `git push` or `gh pr create`.
- Ensure `make quality` passes before committing.
"""
        stats = build_prompt_stats(
            history_before=cause_before + iso_before,
            history_after=cause_after + iso_after,
            section_chars={
                "cause_before": cause_before,
                "cause_after": cause_after,
                "isolation_before": iso_before,
                "isolation_after": iso_after,
            },
        )
        return prompt, stats
