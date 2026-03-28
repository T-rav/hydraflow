"""Tests for the CodeGroomingLoop background worker and audit functions."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from code_grooming_loop import (
    AVAILABLE_AUDITS,
    CodeGroomingLoop,
    _format_issue_body,
    _run_code_quality_audit,
    _run_hooks_audit,
    _run_integration_tests_audit,
    _run_test_adequacy_audit,
    _run_test_quality_audit,
    classify_priority,
    run_audits,
)
from models import (
    AuditFinding,
    CodeGroomingSettings,
    GroomingFiledFinding,
    GroomingPriority,
)
from tests.helpers import make_bg_loop_deps

# ---------------------------------------------------------------------------
# classify_priority
# ---------------------------------------------------------------------------


class TestClassifyPriority:
    def test_security_is_p0(self):
        f = AuditFinding(category="security", summary="sql injection")
        assert classify_priority(f) == GroomingPriority.P0

    def test_critical_severity_is_p0(self):
        f = AuditFinding(category="anything", severity="critical", summary="boom")
        assert classify_priority(f) == GroomingPriority.P0

    def test_missing_tests_is_p1(self):
        f = AuditFinding(category="missing_tests", summary="no tests for foo")
        assert classify_priority(f) == GroomingPriority.P1

    def test_broken_functionality_is_p1(self):
        f = AuditFinding(category="broken_functionality", summary="crash")
        assert classify_priority(f) == GroomingPriority.P1

    def test_duplication_is_p2(self):
        f = AuditFinding(category="duplication", summary="dup")
        assert classify_priority(f) == GroomingPriority.P2

    def test_complexity_is_p2(self):
        f = AuditFinding(category="complexity", summary="too complex")
        assert classify_priority(f) == GroomingPriority.P2

    def test_coverage_gap_is_p2(self):
        f = AuditFinding(category="coverage_gap", summary="gap")
        assert classify_priority(f) == GroomingPriority.P2

    def test_other_category_is_p3(self):
        f = AuditFinding(category="naming", summary="bad name")
        assert classify_priority(f) == GroomingPriority.P3


# ---------------------------------------------------------------------------
# Individual audit functions
# ---------------------------------------------------------------------------


class TestCodeQualityAudit:
    def test_finds_long_functions(self, tmp_path: Path):
        """A function >200 lines should be flagged."""
        src = tmp_path / "src"
        src.mkdir()
        lines = ["def long_func():\n"] + ["    x = 1\n"] * 210
        (src / "big.py").write_text("".join(lines))
        findings = _run_code_quality_audit(tmp_path)
        assert len(findings) >= 1
        assert findings[0].category == "complexity"
        assert "long_func" in findings[0].summary

    def test_no_findings_for_short_functions(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "small.py").write_text("def short():\n    return 1\n")
        findings = _run_code_quality_audit(tmp_path)
        assert findings == []

    def test_no_src_dir(self, tmp_path: Path):
        findings = _run_code_quality_audit(tmp_path)
        assert findings == []


class TestTestQualityAudit:
    def test_finds_missing_test_file(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        tests = tmp_path / "tests"
        tests.mkdir()
        (src / "module_a.py").write_text("x = 1\n")
        findings = _run_test_quality_audit(tmp_path)
        assert len(findings) == 1
        assert findings[0].category == "missing_tests"
        assert "module_a" in findings[0].summary

    def test_no_finding_when_test_exists(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        tests = tmp_path / "tests"
        tests.mkdir()
        (src / "module_a.py").write_text("x = 1\n")
        (tests / "test_module_a.py").write_text("def test_x(): pass\n")
        findings = _run_test_quality_audit(tmp_path)
        assert findings == []

    def test_skips_private_modules(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        tests = tmp_path / "tests"
        tests.mkdir()
        (src / "_internal.py").write_text("x = 1\n")
        findings = _run_test_quality_audit(tmp_path)
        assert findings == []


class TestTestAdequacyAudit:
    def test_flags_low_assertion_count(self, tmp_path: Path):
        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "test_foo.py").write_text(
            "def test_one():\n    pass\ndef test_two():\n    pass\n"
        )
        findings = _run_test_adequacy_audit(tmp_path)
        assert len(findings) == 1
        assert findings[0].category == "coverage_gap"

    def test_no_finding_when_adequate(self, tmp_path: Path):
        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "test_bar.py").write_text(
            "def test_one():\n    assert True\ndef test_two():\n    assert 1 == 1\n"
        )
        findings = _run_test_adequacy_audit(tmp_path)
        assert findings == []


class TestHooksAudit:
    def test_missing_githooks_dir(self, tmp_path: Path):
        findings = _run_hooks_audit(tmp_path)
        assert len(findings) == 1
        assert findings[0].category == "workflow"

    def test_installed_hook_ok(self, tmp_path: Path):
        hooks = tmp_path / ".githooks"
        hooks.mkdir()
        git_hooks = tmp_path / ".git" / "hooks"
        git_hooks.mkdir(parents=True)
        (hooks / "pre-commit").write_text("#!/bin/sh\n")
        (git_hooks / "pre-commit").write_text("#!/bin/sh\n")
        findings = _run_hooks_audit(tmp_path)
        assert findings == []

    def test_uninstalled_hook_flagged(self, tmp_path: Path):
        hooks = tmp_path / ".githooks"
        hooks.mkdir()
        git_hooks = tmp_path / ".git" / "hooks"
        git_hooks.mkdir(parents=True)
        (hooks / "pre-commit").write_text("#!/bin/sh\n")
        findings = _run_hooks_audit(tmp_path)
        assert len(findings) == 1
        assert "pre-commit" in findings[0].summary


class TestIntegrationTestsAudit:
    def test_no_integration_dir(self, tmp_path: Path):
        tests = tmp_path / "tests"
        tests.mkdir()
        findings = _run_integration_tests_audit(tmp_path)
        assert len(findings) == 1
        assert findings[0].category == "coverage_gap"

    def test_has_integration_dir(self, tmp_path: Path):
        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "integration").mkdir()
        findings = _run_integration_tests_audit(tmp_path)
        assert findings == []


# ---------------------------------------------------------------------------
# run_audits orchestrator
# ---------------------------------------------------------------------------


class TestRunAudits:
    def test_runs_enabled_audits(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        tests = tmp_path / "tests"
        tests.mkdir()
        (src / "module.py").write_text("x = 1\n")
        findings = run_audits(tmp_path, ["test_quality"])
        assert any(f.audit_source == "test_quality" for f in findings)

    def test_skips_unknown_audit(self, tmp_path: Path):
        findings = run_audits(tmp_path, ["nonexistent_audit"])
        assert findings == []

    def test_assigns_priorities_and_dedup_keys(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        tests = tmp_path / "tests"
        tests.mkdir()
        (src / "mod.py").write_text("x = 1\n")
        findings = run_audits(tmp_path, ["test_quality"])
        for f in findings:
            assert f.priority in (
                GroomingPriority.P0,
                GroomingPriority.P1,
                GroomingPriority.P2,
                GroomingPriority.P3,
            )
            assert f.dedup_key

    def test_sorted_by_priority(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        tests = tmp_path / "tests"
        tests.mkdir()
        # Create files that will produce findings at different priorities
        (src / "module.py").write_text("x = 1\n")
        findings = run_audits(tmp_path, list(AVAILABLE_AUDITS))
        if len(findings) > 1:
            from code_grooming_loop import _PRIORITY_ORDER

            orders = [_PRIORITY_ORDER.get(f.priority, 99) for f in findings]
            assert orders == sorted(orders)


# ---------------------------------------------------------------------------
# _format_issue_body
# ---------------------------------------------------------------------------


class TestFormatIssueBody:
    def test_contains_dedup_marker(self):
        f = AuditFinding(
            category="complexity",
            summary="too long",
            dedup_key="abc123",
            audit_source="code_quality",
        )
        body = _format_issue_body(f)
        assert "grooming-dedup:abc123" in body

    def test_contains_details(self):
        f = AuditFinding(
            category="complexity",
            summary="too long",
            detail="Some detail here",
            affected_files=["src/foo.py"],
            suggested_fix="Split it up",
            dedup_key="xyz",
            audit_source="code_quality",
        )
        body = _format_issue_body(f)
        assert "Some detail here" in body
        assert "src/foo.py" in body
        assert "Split it up" in body


# ---------------------------------------------------------------------------
# CodeGroomingSettings model
# ---------------------------------------------------------------------------


class TestCodeGroomingSettings:
    def test_defaults(self):
        s = CodeGroomingSettings()
        assert s.max_issues_per_cycle == 5
        assert s.min_priority == GroomingPriority.P1
        assert len(s.enabled_audits) == 5
        assert s.dry_run is False

    def test_custom_settings(self):
        s = CodeGroomingSettings(
            max_issues_per_cycle=3,
            min_priority=GroomingPriority.P0,
            enabled_audits=["code_quality"],
            dry_run=True,
        )
        assert s.max_issues_per_cycle == 3
        assert s.min_priority == GroomingPriority.P0
        assert s.enabled_audits == ["code_quality"]
        assert s.dry_run is True


# ---------------------------------------------------------------------------
# CodeGroomingLoop._do_work
# ---------------------------------------------------------------------------


def _make_loop(
    tmp_path: Path,
    *,
    enabled: bool = True,
    settings: CodeGroomingSettings | None = None,
    filed_findings: list[GroomingFiledFinding] | None = None,
) -> tuple[CodeGroomingLoop, MagicMock, MagicMock]:
    """Build a CodeGroomingLoop with mock dependencies."""
    deps = make_bg_loop_deps(tmp_path, enabled=enabled, code_grooming_interval=3600)

    # Create minimal repo structure
    src = deps.config.repo_root
    src.mkdir(parents=True, exist_ok=True)

    prs = MagicMock()
    prs.create_issue = AsyncMock(return_value=42)

    state = MagicMock()
    state.get_code_grooming_settings.return_value = settings or CodeGroomingSettings()
    state.get_grooming_filed_findings.return_value = filed_findings or []
    state.has_grooming_dedup_key.return_value = False

    loop = CodeGroomingLoop(
        config=deps.config,
        prs=prs,
        state=state,
        deps=deps.loop_deps,
    )
    return loop, prs, state


class TestCodeGroomingLoopDoWork:
    @pytest.mark.asyncio
    async def test_files_issues_for_findings(self, tmp_path: Path):
        loop, prs, state = _make_loop(tmp_path)
        # Create a source file with no test
        src = Path(loop._config.repo_root) / "src"
        src.mkdir(parents=True, exist_ok=True)
        tests = Path(loop._config.repo_root) / "tests"
        tests.mkdir(parents=True, exist_ok=True)
        (src / "untested.py").write_text("x = 1\n")

        result = await loop._do_work()
        assert result is not None
        assert result["findings_total"] > 0
        assert result["issues_filed"] > 0
        prs.create_issue.assert_called()
        state.add_grooming_filed_finding.assert_called()

    @pytest.mark.asyncio
    async def test_dry_run_no_issues_created(self, tmp_path: Path):
        settings = CodeGroomingSettings(dry_run=True)
        loop, prs, state = _make_loop(tmp_path, settings=settings)
        src = Path(loop._config.repo_root) / "src"
        src.mkdir(parents=True, exist_ok=True)
        tests = Path(loop._config.repo_root) / "tests"
        tests.mkdir(parents=True, exist_ok=True)
        (src / "untested.py").write_text("x = 1\n")

        result = await loop._do_work()
        assert result is not None
        assert result["dry_run"] is True
        assert result["issues_filed"] == 0
        prs.create_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_deduplication_skips_known(self, tmp_path: Path):
        loop, prs, state = _make_loop(tmp_path)
        state.has_grooming_dedup_key.return_value = True
        src = Path(loop._config.repo_root) / "src"
        src.mkdir(parents=True, exist_ok=True)
        tests = Path(loop._config.repo_root) / "tests"
        tests.mkdir(parents=True, exist_ok=True)
        (src / "untested.py").write_text("x = 1\n")

        result = await loop._do_work()
        assert result is not None
        assert result["findings_novel"] == 0
        assert result["issues_filed"] == 0
        prs.create_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_max_issues_cap(self, tmp_path: Path):
        settings = CodeGroomingSettings(max_issues_per_cycle=1)
        loop, prs, state = _make_loop(tmp_path, settings=settings)
        src = Path(loop._config.repo_root) / "src"
        src.mkdir(parents=True, exist_ok=True)
        tests = Path(loop._config.repo_root) / "tests"
        tests.mkdir(parents=True, exist_ok=True)
        # Create multiple untested files
        (src / "a.py").write_text("x = 1\n")
        (src / "b.py").write_text("y = 2\n")
        (src / "c.py").write_text("z = 3\n")

        result = await loop._do_work()
        assert result is not None
        # Should file at most 1 issue
        assert result["issues_filed"] <= 1

    @pytest.mark.asyncio
    async def test_priority_filter(self, tmp_path: Path):
        settings = CodeGroomingSettings(min_priority=GroomingPriority.P0)
        loop, prs, state = _make_loop(tmp_path, settings=settings)
        src = Path(loop._config.repo_root) / "src"
        src.mkdir(parents=True, exist_ok=True)
        tests = Path(loop._config.repo_root) / "tests"
        tests.mkdir(parents=True, exist_ok=True)
        # Missing test files are P1, should be filtered out with P0-only
        (src / "untested.py").write_text("x = 1\n")

        result = await loop._do_work()
        assert result is not None
        assert result["findings_filtered"] == 0
        assert result["issues_filed"] == 0

    @pytest.mark.asyncio
    async def test_default_interval(self, tmp_path: Path):
        loop, _, _ = _make_loop(tmp_path)
        assert loop._get_default_interval() == 3600  # from config override

    @pytest.mark.asyncio
    async def test_issue_labels_include_hydraflow_find(self, tmp_path: Path):
        loop, prs, state = _make_loop(tmp_path)
        src = Path(loop._config.repo_root) / "src"
        src.mkdir(parents=True, exist_ok=True)
        tests = Path(loop._config.repo_root) / "tests"
        tests.mkdir(parents=True, exist_ok=True)
        (src / "untested.py").write_text("x = 1\n")

        await loop._do_work()
        if prs.create_issue.called:
            call_kwargs = prs.create_issue.call_args
            labels = call_kwargs.kwargs.get("labels", [])
            assert "hydraflow-find" in labels

    @pytest.mark.asyncio
    async def test_create_issue_failure_counts_as_skipped(self, tmp_path: Path):
        loop, prs, state = _make_loop(tmp_path)
        prs.create_issue = AsyncMock(return_value=0)  # failure
        src = Path(loop._config.repo_root) / "src"
        src.mkdir(parents=True, exist_ok=True)
        tests = Path(loop._config.repo_root) / "tests"
        tests.mkdir(parents=True, exist_ok=True)
        (src / "untested.py").write_text("x = 1\n")

        result = await loop._do_work()
        assert result is not None
        assert result["issues_filed"] == 0
        assert result["issues_skipped"] > 0
