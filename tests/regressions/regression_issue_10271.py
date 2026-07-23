"""Regression test for issue #10271.

Bug: ``scope_check.build_scope_check_prompt`` has only two outcomes — auto-pass
when no plan is available, or compare the branch diff's changed files against the
plan's declared File Delta and flag anything not in that list as scope creep
(WARN/FAIL). There is NO success path for a landing-only / verification-only task
whose correct terminal state is "no relevant code diff."

Real occurrence (#10258): a landing-only task correctly produced zero relevant
diff after a human merged the target PR out-of-band, but leftover unrelated files
from earlier rejected sub-efforts on the branch got flagged as scope creep,
failing an objectively-correct attempt.

Expected behaviour after fix:
  - A plan can declare a landing-only / verification-only task (task-type marker).
  - When such a plan is declared AND the diff touches none of the plan's declared
    files, scope-check auto-passes (SCOPE_CHECK_RESULT: OK) instead of routing the
    unrelated residue through FAIL/RETRY classification.
  - Genuine scope creep is still detectable: if the diff touches a planned file
    (real changes) alongside unrelated files, the auto-pass is NOT taken and the
    normal classification prompt is produced.
  - A code-change task (no landing-only marker) is NEVER auto-passed by this path,
    so a genuine silent-failure-via-empty-diff is not masked.

These tests assert the CORRECT (post-fix) behaviour and are therefore RED
against the current code.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from delta_verifier import is_landing_only_plan, parse_task_type
from scope_check import build_scope_check_prompt

_AUTO_PASS_MARKER = "SCOPE_CHECK_RESULT: OK"
# The classification prompt (real scope-creep review) emits the OK|RETRY choice.
_CLASSIFICATION_MARKER = "SCOPE_CHECK_RESULT: OK|RETRY"


class TestLandingOnlyMarkerParsing:
    """The plan format can carry a landing-only / verification-only signal."""

    def test_task_type_section_parsed(self):
        plan = "## Task Type\nlanding-only\n\n## File Delta\n"
        assert parse_task_type(plan) == "landing-only"

    def test_inline_task_type_marker_parsed(self):
        plan = "Some plan prose.\nTASK_TYPE: verification-only\n"
        assert parse_task_type(plan) == "verification-only"

    def test_no_marker_returns_none(self):
        plan = "## File Delta\nMODIFIED: src/foo.py\n"
        assert parse_task_type(plan) is None

    def test_landing_only_recognised(self):
        assert is_landing_only_plan("## Task Type\nlanding-only\n") is True

    def test_verification_only_recognised(self):
        assert is_landing_only_plan("## Task Type\nverification-only\n") is True

    def test_separator_normalisation(self):
        # underscores / spaces must normalise to the recognised hyphen form
        assert is_landing_only_plan("TASK_TYPE: landing_only\n") is True
        assert is_landing_only_plan("TASK_TYPE: verification only\n") is True

    def test_code_change_plan_is_not_landing_only(self):
        plan = "## File Delta\nMODIFIED: src/foo.py\n"
        assert is_landing_only_plan(plan) is False


class TestZeroDiffNoOpSuccessPath:
    """The core fix: landing-only tasks pass instead of false scope-creep."""

    def test_landing_only_plus_empty_diff_auto_passes(self):
        plan = "## Task Type\nlanding-only\n\n## File Delta\n"
        prompt = build_scope_check_prompt(
            issue_number=10258,
            issue_title="Land PR #10256",
            diff="",
            plan_text=plan,
        )
        assert _AUTO_PASS_MARKER in prompt
        assert _CLASSIFICATION_MARKER not in prompt

    def test_landing_only_plus_unrelated_residue_auto_passes(self):
        # Diff touches ONLY unrelated leftover residue — none of the plan's files.
        plan = "## Task Type\nlanding-only\n\n## File Delta\nMODIFIED: src/target.py\n"
        residue_diff = (
            "diff --git a/src/residue.py b/src/residue.py\n"
            "--- a/src/residue.py\n"
            "+++ b/src/residue.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        )
        prompt = build_scope_check_prompt(
            issue_number=10258,
            issue_title="Land PR #10256",
            diff=residue_diff,
            plan_text=plan,
        )
        assert _AUTO_PASS_MARKER in prompt
        assert _CLASSIFICATION_MARKER not in prompt

    def test_landing_only_but_touches_planned_file_does_not_auto_pass(self):
        # Conservative guard: if the diff actually touches a planned file
        # (real changes) alongside residue, fall through to classification so
        # genuine "some diff, wrong diff" scope creep is still caught.
        plan = "## Task Type\nlanding-only\n\n## File Delta\nMODIFIED: src/target.py\n"
        mixed_diff = (
            "diff --git a/src/target.py b/src/target.py\n"
            "--- a/src/target.py\n"
            "+++ b/src/target.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
            "diff --git a/src/unrelated.py b/src/unrelated.py\n"
            "--- a/src/unrelated.py\n"
            "+++ b/src/unrelated.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        )
        prompt = build_scope_check_prompt(
            issue_number=10258,
            issue_title="Land PR #10256",
            diff=mixed_diff,
            plan_text=plan,
        )
        assert _CLASSIFICATION_MARKER in prompt

    def test_code_change_plan_plus_empty_diff_not_auto_passed(self):
        # Regression guard against masking a genuine silent no-op failure:
        # a plan WITHOUT the landing-only marker must NOT take the auto-pass path,
        # even on an empty diff. It falls through to normal classification.
        plan = "## File Delta\nMODIFIED: src/foo.py\n"
        prompt = build_scope_check_prompt(
            issue_number=42,
            issue_title="Implement feature",
            diff="",
            plan_text=plan,
        )
        assert _CLASSIFICATION_MARKER in prompt

    def test_code_change_plan_with_scope_creep_still_classifies(self):
        # Ordinary scope-creep review is unchanged for non-landing plans.
        plan = "## File Delta\nMODIFIED: src/foo.py\n"
        diff = (
            "diff --git a/src/auth.py b/src/auth.py\n"
            "--- a/src/auth.py\n"
            "+++ b/src/auth.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        )
        prompt = build_scope_check_prompt(
            issue_number=42,
            issue_title="Implement feature",
            diff=diff,
            plan_text=plan,
        )
        assert _CLASSIFICATION_MARKER in prompt
        assert "src/auth.py" in prompt
