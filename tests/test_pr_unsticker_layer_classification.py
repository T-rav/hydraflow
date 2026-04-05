"""Tests that pr_unsticker.py is correctly classified as Layer 2 (Application).

Verifies the architecture documentation in hf.audit-architecture.md and CLAUDE.md
classifies pr_unsticker.py as a workflow coordinator (Layer 2), not infrastructure
(Layer 4).

Ref: gh-5965
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
AUDIT_PATH = ROOT / ".claude" / "commands" / "hf.audit-architecture.md"
CLAUDE_MD_PATH = ROOT / "CLAUDE.md"


@pytest.fixture()
def audit_text() -> str:
    return AUDIT_PATH.read_text()


@pytest.fixture()
def claude_md_text() -> str:
    return CLAUDE_MD_PATH.read_text()


# ── Architecture audit: overview block ────────────────────────────


class TestAuditOverviewBlock:
    """Verify pr_unsticker.py placement in the fenced-code overview block."""

    def _extract_layer_block(self, text: str, layer_prefix: str) -> str:
        """Return all lines belonging to a layer in the overview block."""
        lines = text.splitlines()
        collecting = False
        result: list[str] = []
        for line in lines:
            if line.startswith(layer_prefix):
                collecting = True
            elif collecting and (
                line.startswith("Layer ") or line.startswith("Cross-cutting")
            ):
                break
            if collecting:
                result.append(line)
        return "\n".join(result)

    def test_pr_unsticker_in_layer2(self, audit_text: str) -> None:
        block = self._extract_layer_block(audit_text, "Layer 2")
        assert "pr_unsticker.py" in block

    def test_pr_unsticker_not_in_layer4(self, audit_text: str) -> None:
        block = self._extract_layer_block(audit_text, "Layer 4")
        assert "pr_unsticker.py" not in block


# ── Architecture audit: Agent 1 table ────────────────────────────


class TestAuditAgentTable:
    """Verify pr_unsticker.py placement in the Agent 1 layer assignment table."""

    def _extract_table_row(self, text: str, layer_label: str) -> str:
        """Return the table row containing `layer_label`."""
        for line in text.splitlines():
            if line.startswith("|") and layer_label in line:
                return line
        pytest.fail(f"No table row found containing '{layer_label}'")

    def test_pr_unsticker_in_layer2_row(self, audit_text: str) -> None:
        row = self._extract_table_row(audit_text, "2 — Application")
        assert "pr_unsticker.py" in row

    def test_pr_unsticker_not_in_layer4_row(self, audit_text: str) -> None:
        row = self._extract_table_row(audit_text, "4 — Infrastructure")
        assert "pr_unsticker.py" not in row


# ── CLAUDE.md Key Files grouping ─────────────────────────────────


class TestClaudeMdKeyFiles:
    """Verify pr_unsticker.py is listed under Phase implementations, not Git & PR."""

    def _extract_section(self, text: str, header: str) -> str:
        """Return lines between `header` and the next bold header or section."""
        lines = text.splitlines()
        collecting = False
        result: list[str] = []
        for line in lines:
            if header in line:
                collecting = True
                continue
            if collecting and line.startswith("**") and line.endswith("**"):
                break
            if collecting:
                result.append(line)
        return "\n".join(result)

    def test_pr_unsticker_in_phase_implementations(self, claude_md_text: str) -> None:
        section = self._extract_section(claude_md_text, "**Phase implementations:**")
        assert "pr_unsticker.py" in section

    def test_pr_unsticker_not_in_git_pr_management(self, claude_md_text: str) -> None:
        section = self._extract_section(claude_md_text, "**Git & PR management:**")
        assert "pr_unsticker.py" not in section

    def test_pr_unsticker_loop_still_in_background_loops(
        self, claude_md_text: str
    ) -> None:
        section = self._extract_section(claude_md_text, "**Background loops:**")
        assert "pr_unsticker_loop.py" in section


# ── No other modules displaced ───────────────────────────────────


class TestNoCollateralChanges:
    """Ensure no other modules were accidentally moved between layers."""

    LAYER4_EXPECTED = {
        "pr_manager.py",
        "worktree.py",
        "merge_conflict_resolver.py",
        "post_merge_handler.py",
        "dashboard.py",
    }

    def test_layer4_modules_preserved(self, audit_text: str) -> None:
        """All expected Layer 4 modules still appear in Layer 4 overview block."""
        lines = audit_text.splitlines()
        collecting = False
        layer4_text = ""
        for line in lines:
            if line.startswith("Layer 4"):
                collecting = True
            elif collecting and (
                line.startswith("Layer ") or line.startswith("Cross-cutting")
            ):
                break
            if collecting:
                layer4_text += line + "\n"
        for mod in self.LAYER4_EXPECTED:
            assert mod in layer4_text, f"{mod} missing from Layer 4"
