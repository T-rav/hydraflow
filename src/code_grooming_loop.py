"""Background worker loop — periodic code grooming audits that file prioritized issues."""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from models import AuditFinding, GroomingFiledFinding, GroomingPriority

if TYPE_CHECKING:
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.code_grooming")

# Audit names that can be toggled in settings.
AVAILABLE_AUDITS = frozenset(
    {
        "code_quality",
        "test_quality",
        "test_adequacy",
        "hooks",
        "integration_tests",
    }
)

_PRIORITY_ORDER = {
    GroomingPriority.P0: 0,
    GroomingPriority.P1: 1,
    GroomingPriority.P2: 2,
    GroomingPriority.P3: 3,
}


def classify_priority(finding: AuditFinding) -> GroomingPriority:
    """Assign a priority level to an audit finding."""
    if finding.category == "security" or finding.severity == "critical":
        return GroomingPriority.P0
    if finding.category in ("missing_tests", "broken_functionality"):
        return GroomingPriority.P1
    if finding.category in ("duplication", "complexity", "coverage_gap"):
        return GroomingPriority.P2
    return GroomingPriority.P3


def _dedup_key_for(finding: AuditFinding) -> str:
    """Generate a stable dedup key from a finding's core attributes."""
    if finding.dedup_key:
        return finding.dedup_key
    raw = f"{finding.category}:{finding.audit_source}:{finding.summary}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Individual audit implementations
# ---------------------------------------------------------------------------


def _run_code_quality_audit(repo_root: Path) -> list[AuditFinding]:
    """Scan Python files for code quality issues (complexity, long functions)."""
    findings: list[AuditFinding] = []
    src_dir = repo_root / "src"
    if not src_dir.is_dir():
        return findings

    for py_file in src_dir.rglob("*.py"):
        if py_file.name.startswith("_") and py_file.name != "__init__.py":
            continue
        try:
            content = py_file.read_text(errors="replace")
        except OSError:
            continue
        lines = content.splitlines()

        # Check for overly long functions (>200 lines)
        func_start: int | None = None
        func_name: str = ""
        for i, line in enumerate(lines):
            match = re.match(r"^(\s*)(async\s+)?def\s+(\w+)", line)
            if match:
                if func_start is not None:
                    length = i - func_start
                    if length > 200:
                        rel = str(py_file.relative_to(repo_root))
                        findings.append(
                            AuditFinding(
                                category="complexity",
                                severity="medium",
                                summary=f"Function `{func_name}` is {length} lines long",
                                detail=f"{rel}:{func_start + 1} — consider splitting.",
                                affected_files=[rel],
                                suggested_fix="Break into smaller helper functions.",
                                audit_source="code_quality",
                            )
                        )
                func_start = i
                func_name = match.group(3)

        # Check final function
        if func_start is not None:
            length = len(lines) - func_start
            if length > 200:
                rel = str(py_file.relative_to(repo_root))
                findings.append(
                    AuditFinding(
                        category="complexity",
                        severity="medium",
                        summary=f"Function `{func_name}` is {length} lines long",
                        detail=f"{rel}:{func_start + 1} — consider splitting.",
                        affected_files=[rel],
                        suggested_fix="Break into smaller helper functions.",
                        audit_source="code_quality",
                    )
                )

        # Check for duplicate code blocks (simple heuristic: repeated 5+ line blocks)
        # This is intentionally lightweight — a full duplication detector is out of scope.

    return findings


def _run_test_quality_audit(repo_root: Path) -> list[AuditFinding]:
    """Check for missing test files for source modules."""
    findings: list[AuditFinding] = []
    src_dir = repo_root / "src"
    tests_dir = repo_root / "tests"
    if not src_dir.is_dir() or not tests_dir.is_dir():
        return findings

    existing_tests = {p.name for p in tests_dir.glob("test_*.py")}

    for py_file in src_dir.glob("*.py"):
        if py_file.name.startswith("_"):
            continue
        expected_test = f"test_{py_file.stem}.py"
        if expected_test not in existing_tests:
            rel = str(py_file.relative_to(repo_root))
            findings.append(
                AuditFinding(
                    category="missing_tests",
                    severity="high",
                    summary=f"No test file for `{py_file.name}`",
                    detail=f"Expected `tests/{expected_test}` but not found.",
                    affected_files=[rel],
                    suggested_fix=f"Create `tests/{expected_test}` with unit tests.",
                    audit_source="test_quality",
                )
            )

    return findings


def _run_test_adequacy_audit(repo_root: Path) -> list[AuditFinding]:
    """Check test files for minimal assertion counts."""
    findings: list[AuditFinding] = []
    tests_dir = repo_root / "tests"
    if not tests_dir.is_dir():
        return findings

    for test_file in tests_dir.glob("test_*.py"):
        try:
            content = test_file.read_text(errors="replace")
        except OSError:
            continue

        test_funcs = re.findall(
            r"^(?:async\s+)?def\s+(test_\w+)", content, re.MULTILINE
        )
        assert_count = len(re.findall(r"\bassert\b", content))
        if test_funcs and assert_count < len(test_funcs):
            rel = str(test_file.relative_to(repo_root))
            findings.append(
                AuditFinding(
                    category="coverage_gap",
                    severity="medium",
                    summary=f"`{test_file.name}` has fewer assertions ({assert_count}) than test functions ({len(test_funcs)})",
                    detail="Some test functions may lack proper assertions.",
                    affected_files=[rel],
                    suggested_fix="Add assertions to test functions missing them.",
                    audit_source="test_adequacy",
                )
            )

    return findings


def _run_hooks_audit(repo_root: Path) -> list[AuditFinding]:
    """Check for missing or misconfigured git hooks."""
    findings: list[AuditFinding] = []
    hooks_dir = repo_root / ".githooks"
    git_hooks_dir = repo_root / ".git" / "hooks"

    if not hooks_dir.is_dir():
        findings.append(
            AuditFinding(
                category="workflow",
                severity="low",
                summary="No `.githooks/` directory found",
                detail="Project may be missing shared git hook definitions.",
                audit_source="hooks",
            )
        )
        return findings

    # Check that hooks are installed (symlinked or copied)
    for hook_file in hooks_dir.iterdir():
        if hook_file.is_file() and not hook_file.name.startswith("."):
            installed = git_hooks_dir / hook_file.name
            if not installed.exists():
                findings.append(
                    AuditFinding(
                        category="workflow",
                        severity="low",
                        summary=f"Git hook `{hook_file.name}` is not installed",
                        detail=f"`.githooks/{hook_file.name}` exists but `.git/hooks/{hook_file.name}` does not.",
                        affected_files=[f".githooks/{hook_file.name}"],
                        suggested_fix="Run `make setup` to install hooks.",
                        audit_source="hooks",
                    )
                )

    return findings


def _run_integration_tests_audit(repo_root: Path) -> list[AuditFinding]:
    """Check for integration test gaps."""
    findings: list[AuditFinding] = []
    tests_dir = repo_root / "tests"
    if not tests_dir.is_dir():
        return findings

    has_integration = any(tests_dir.glob("*integration*"))
    if not has_integration:
        # Check if there's an integration test directory at all
        integ_dir = tests_dir / "integration"
        if not integ_dir.is_dir():
            findings.append(
                AuditFinding(
                    category="coverage_gap",
                    severity="medium",
                    summary="No integration test directory found",
                    detail="Expected `tests/integration/` or files matching `*integration*`.",
                    suggested_fix="Create integration tests for cross-module interactions.",
                    audit_source="integration_tests",
                )
            )

    return findings


# ---------------------------------------------------------------------------
# Audit dispatcher
# ---------------------------------------------------------------------------

_AUDIT_RUNNERS: dict[str, Any] = {
    "code_quality": _run_code_quality_audit,
    "test_quality": _run_test_quality_audit,
    "test_adequacy": _run_test_adequacy_audit,
    "hooks": _run_hooks_audit,
    "integration_tests": _run_integration_tests_audit,
}


def run_audits(
    repo_root: Path,
    enabled_audits: list[str],
) -> list[AuditFinding]:
    """Execute the enabled audits and return all findings with priorities assigned."""
    all_findings: list[AuditFinding] = []
    for audit_name in enabled_audits:
        runner = _AUDIT_RUNNERS.get(audit_name)
        if runner is None:
            logger.warning("Unknown audit: %s", audit_name)
            continue
        try:
            findings = runner(repo_root)
            all_findings.extend(findings)
        except Exception:
            logger.exception("Audit %s failed", audit_name)

    # Assign priorities and dedup keys
    for f in all_findings:
        f.priority = classify_priority(f)
        f.dedup_key = _dedup_key_for(f)

    # Sort by priority (P0 first)
    all_findings.sort(key=lambda f: _PRIORITY_ORDER.get(f.priority, 99))
    return all_findings


def _format_issue_body(finding: AuditFinding) -> str:
    """Format an audit finding into a GitHub issue body."""
    parts = [
        f"## {finding.priority.value}: {finding.summary}",
        "",
        f"**Category:** {finding.category}",
        f"**Severity:** {finding.severity}",
        f"**Audit source:** {finding.audit_source}",
    ]
    if finding.detail:
        parts.extend(["", "### Details", "", finding.detail])
    if finding.affected_files:
        parts.extend(["", "### Affected Files", ""])
        for af in finding.affected_files:
            parts.append(f"- `{af}`")
    if finding.suggested_fix:
        parts.extend(["", "### Suggested Fix", "", finding.suggested_fix])
    parts.extend(
        [
            "",
            "---",
            f"<!-- grooming-dedup:{finding.dedup_key} -->",
        ]
    )
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Background loop
# ---------------------------------------------------------------------------


class CodeGroomingLoop(BaseBackgroundLoop):
    """Periodically audits the codebase and files prioritized issues for findings."""

    def __init__(
        self,
        config: HydraFlowConfig,
        prs: PRManager,
        state: StateTracker,
        deps: LoopDeps,
    ) -> None:
        super().__init__(worker_name="code_grooming", config=config, deps=deps)
        self._prs = prs
        self._state = state

    def _get_default_interval(self) -> int:
        return self._config.code_grooming_interval

    async def _do_work(self) -> dict[str, Any] | None:
        """Run configured audits, classify findings, and file issues."""
        settings = self._state.get_code_grooming_settings()
        repo_root = Path(self._config.repo_root)

        # Run audits
        enabled = [a for a in settings.enabled_audits if a in AVAILABLE_AUDITS]
        findings = run_audits(repo_root, enabled)

        # Filter by minimum priority
        min_order = _PRIORITY_ORDER.get(settings.min_priority, 1)
        filtered = [
            f for f in findings if _PRIORITY_ORDER.get(f.priority, 99) <= min_order
        ]

        # Deduplicate against previously filed findings
        novel: list[AuditFinding] = []
        for f in filtered:
            if not self._state.has_grooming_dedup_key(f.dedup_key):
                novel.append(f)

        # Cap to max issues per cycle
        to_file = novel[: settings.max_issues_per_cycle]

        filed = 0
        skipped = 0
        dry_run = settings.dry_run

        for finding in to_file:
            title = f"[Grooming] {finding.priority.value}: {finding.summary}"
            body = _format_issue_body(finding)
            labels = ["hydraflow-find", f"grooming-{finding.priority.value.lower()}"]

            if dry_run:
                logger.info("[dry-run] Would file: %s", title)
                skipped += 1
                continue

            issue_number = await self._prs.create_issue(
                title=title,
                body=body,
                labels=labels,
            )
            if issue_number:
                self._state.add_grooming_filed_finding(
                    GroomingFiledFinding(
                        dedup_key=finding.dedup_key,
                        issue_number=issue_number,
                        title=title,
                        priority=finding.priority,
                    )
                )
                filed += 1
                logger.info("Filed grooming issue #%d: %s", issue_number, title)
            else:
                skipped += 1
                logger.warning("Failed to file issue for: %s", finding.summary)

        return {
            "findings_total": len(findings),
            "findings_filtered": len(filtered),
            "findings_novel": len(novel),
            "issues_filed": filed,
            "issues_skipped": skipped,
            "dry_run": dry_run,
            "audits_run": enabled,
        }
