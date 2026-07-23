"""Regression: P10.3's history scan blamed the wrong PRs (#9902).

The check scanned MERGED history but ran in every open PR's CI, so one
fix landing without a regression test turned every unrelated PR red —
forcing two consent-gated manual baseline advances within three hours
(#9892 at 19:00Z, #9901 at 20:08Z describing the same already-covered
change). An instrument that demands manual exemptions for compliant work
is miscalibrated.

Pins (the enforcement/measurement split):
- P10.3's WARN is telemetry: reported, never flips the audit exit code —
  the "unrelated PR goes red" scenario is structurally dead.
- P10.6 gates the PR's OWN merge-base diff: fix commits without a
  regression delta fail THAT PR only, with an actionable message.
- `Skip-Regression: <why>` trailer opts out (greppable justification).
- A UI-only fix with a src/ui test delta passes without a token Python
  test.
- No `.hydraflow-audit-baseline` edit is required for any of the above.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.hydraflow_audit.checks._helpers import finding
from scripts.hydraflow_audit.checks.p10_tdd import (
    _bug_fixes_land_with_regression_tests,
    _fix_prs_carry_regression_delta,
)
from scripts.hydraflow_audit.models import CheckContext, Status
from scripts.hydraflow_audit.runner import TELEMETRY_CHECKS, overall_exit_code


def _git_env() -> dict[str, str]:
    return {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }


def _git(tmp_path: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=tmp_path, check=True, env=_git_env())


def _commit(tmp_path: Path, subject: str, files: dict[str, str]) -> None:
    for rel, content in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", subject)


def _pr_repo(tmp_path: Path, *, fix_files: dict[str, str], subject: str) -> None:
    """main with one base commit; a fix branch with *fix_files* committed."""
    _git(tmp_path, "init", "-q", "-b", "main")
    _commit(tmp_path, "chore: base", {"src/app.py": "x = 1\n"})
    _git(tmp_path, "checkout", "-q", "-b", "fix/thing")
    _commit(tmp_path, subject, fix_files)


def _ctx(tmp_path: Path) -> CheckContext:
    return CheckContext(root=tmp_path)


class TestTelemetryNeverBlocks:
    def test_p103_warn_does_not_flip_exit_code(self) -> None:
        """The 'unrelated PR goes red' scenario: telemetry WARN exits 0."""
        assert "P10.3" in TELEMETRY_CHECKS
        findings = [
            finding("P10.3", Status.WARN, "3/10 fix commits without a test"),
            finding("P10.2", Status.PASS, ""),
        ]
        assert overall_exit_code(findings) == 0

    def test_p106_warn_still_blocks(self) -> None:
        """Enforcement lives in the per-PR gate — its WARN fails CI."""
        findings = [finding("P10.6", Status.WARN, "no regression delta")]
        assert overall_exit_code(findings) == 1

    def test_p103_message_names_the_split(self, tmp_path: Path) -> None:
        _git(tmp_path, "init", "-q", "-b", "main")
        _commit(tmp_path, "fix(app): repair crash", {"src/app.py": "x = 2\n"})
        result = _bug_fixes_land_with_regression_tests(_ctx(tmp_path))
        assert result.status is Status.WARN
        assert "telemetry" in (result.message or "")
        assert "P10.6" in (result.message or "")


class TestPerPrGate:
    def test_fix_pr_without_regression_delta_fails_that_pr(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pr_repo(
            tmp_path,
            subject="fix(app): repair crash",
            fix_files={"src/app.py": "x = 2\n"},
        )
        monkeypatch.setenv("HYDRAFLOW_AUDIT_PR_BASE", "main")

        result = _fix_prs_carry_regression_delta(_ctx(tmp_path))

        assert result.status is Status.WARN
        assert "tests/regressions/" in (result.message or "")
        assert "Skip-Regression" in (result.message or "")

    def test_fix_pr_with_regression_delta_passes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pr_repo(
            tmp_path,
            subject="fix(app): repair crash",
            fix_files={
                "src/app.py": "x = 2\n",
                "tests/regressions/test_issue_1_crash.py": "def test_x(): pass\n",
            },
        )
        monkeypatch.setenv("HYDRAFLOW_AUDIT_PR_BASE", "main")

        result = _fix_prs_carry_regression_delta(_ctx(tmp_path))

        assert result.status is Status.PASS

    def test_ci_workflow_only_fix_is_exempt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A fix(...) PR that only touches .github/ (CI/workflow) cannot carry a
        # Python or UI regression test. P10.6 previously fell through to WARN and
        # reddened every such PR (e.g. fix(ci): CodeQL trigger change). With no
        # product-code delta, the gate must PASS.
        _pr_repo(
            tmp_path,
            subject="fix(ci): run CodeQL on staging",
            fix_files={
                ".github/workflows/codeql.yml": "on:\n  push:\n    branches: [main]\n",
                ".github/codeql/codeql-config.yml": "paths-ignore:\n  - tests/**\n",
            },
        )
        monkeypatch.setenv("HYDRAFLOW_AUDIT_PR_BASE", "main")

        result = _fix_prs_carry_regression_delta(_ctx(tmp_path))

        assert result.status is Status.PASS
        assert "not applicable" in (result.message or "")

    def test_skip_regression_trailer_opts_out_with_reason(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pr_repo(
            tmp_path,
            subject=(
                "fix(app): repair crash\n\n"
                "Coverage lives in tests/test_app.py::test_crash_path.\n\n"
                "Skip-Regression: covered by existing test_crash_path pins"
            ),
            fix_files={"src/app.py": "x = 2\n"},
        )
        monkeypatch.setenv("HYDRAFLOW_AUDIT_PR_BASE", "main")

        result = _fix_prs_carry_regression_delta(_ctx(tmp_path))

        assert result.status is Status.PASS
        assert "covered by existing test_crash_path pins" in (result.message or "")

    def test_ui_only_fix_with_ui_test_delta_passes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pr_repo(
            tmp_path,
            subject="fix(ui): cap dots",
            fix_files={
                "src/ui/src/components/StreamView.jsx": "cap\n",
                "src/ui/src/components/__tests__/StreamView.test.jsx": "t\n",
            },
        )
        monkeypatch.setenv("HYDRAFLOW_AUDIT_PR_BASE", "main")

        result = _fix_prs_carry_regression_delta(_ctx(tmp_path))

        assert result.status is Status.PASS
        assert "UI" in (result.message or "")

    def test_ui_only_fix_without_ui_test_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pr_repo(
            tmp_path,
            subject="fix(ui): cap dots",
            fix_files={"src/ui/src/components/StreamView.jsx": "cap\n"},
        )
        monkeypatch.setenv("HYDRAFLOW_AUDIT_PR_BASE", "main")

        result = _fix_prs_carry_regression_delta(_ctx(tmp_path))

        assert result.status is Status.WARN

    def test_off_pr_context_is_na(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Local audits and push builds never trip the gate."""
        _pr_repo(
            tmp_path,
            subject="fix(app): repair crash",
            fix_files={"src/app.py": "x = 2\n"},
        )
        monkeypatch.delenv("HYDRAFLOW_AUDIT_PR_BASE", raising=False)

        result = _fix_prs_carry_regression_delta(_ctx(tmp_path))

        assert result.status is Status.NA

    def test_non_fix_pr_passes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pr_repo(
            tmp_path,
            subject="feat(app): add feature",
            fix_files={"src/app.py": "x = 2\n"},
        )
        monkeypatch.setenv("HYDRAFLOW_AUDIT_PR_BASE", "main")

        result = _fix_prs_carry_regression_delta(_ctx(tmp_path))

        assert result.status is Status.PASS

    def test_test_only_fix_commit_is_not_gated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test-maintenance fixes need no ADDITIONAL regression test."""
        _pr_repo(
            tmp_path,
            subject="fix(tests): stabilize flaky pin",
            fix_files={"tests/test_app.py": "def test_x(): pass\n"},
        )
        monkeypatch.setenv("HYDRAFLOW_AUDIT_PR_BASE", "main")

        result = _fix_prs_carry_regression_delta(_ctx(tmp_path))

        assert result.status is Status.PASS
