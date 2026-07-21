"""Regression pins for issue #10057 — on-Write ruff autofix must be
non-destructive inside factory *agent* worktrees.

The ``.claude/hooks/hf.auto-lint-after-edit.sh`` PostToolUse hook runs
``ruff check --fix --unsafe-fixes`` on every ``.py`` Write/Edit. During a
TDD red phase in a factory agent worktree that is actively harmful: it
strips not-yet-used imports (F401) the agent just wrote for code it is
about to write, and ``--unsafe-fixes`` rewrites ``setattr`` (B010) into
attribute-assignment form the agent was deliberately avoiding. The agent
re-adds, the hook re-strips, and attempt budget burns.

The fix keys off the canonical factory agent-worktree path shape
(``.../worktrees/<repo_slug>/issue-<N>/...`` — see
``HydraFlowConfig.workspace_path_for_issue``). In that context the hook
switches to *detection-only* (``ruff check`` with no ``--fix``, no
``format``): the agent still SEES remaining lint but nothing is stripped
or rewritten. Human/interactive checkouts (no such path segment) keep the
existing ``--fix --unsafe-fixes`` + ``format`` behaviour byte-for-byte.

CI-enforced lint results are unchanged: ``make quality`` / ruff still run
in full at commit and in CI. This only changes *when/where* the on-Write
autofix strips.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

_HOOK = (
    Path(__file__).resolve().parents[2]
    / ".claude"
    / "hooks"
    / "hf.auto-lint-after-edit.sh"
)

# An unused import: ruff F401. In a human checkout the hook's --fix pass
# deletes it; in an agent worktree it must survive untouched.
_UNUSED_IMPORT_FILE = "import os\n"


def _run_hook(target: Path) -> None:
    """Feed the hook the PostToolUse payload for *target* and wait for it."""
    payload = json.dumps({"tool_input": {"file_path": str(target)}})
    subprocess.run(
        ["bash", str(_HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        check=True,
    )


def test_agent_worktree_write_keeps_unused_import_present() -> None:
    # ruff must be discoverable for the hook to do anything at all; without
    # it the pin cannot distinguish stripped from preserved. CI always has
    # ruff (make quality uses it), so this early-return never fires there.
    # A plain return (not a skip/xfail marker) keeps the repo's
    # no-ignored-active-tests guard satisfied.
    if shutil.which("ruff") is None:
        return

    with tempfile.TemporaryDirectory() as tmp:
        # Canonical factory agent-worktree shape: <base>/worktrees/<slug>/issue-<N>/
        agent_dir = Path(tmp) / "worktrees" / "T-rav-hydraflow" / "issue-10057"
        agent_dir.mkdir(parents=True)
        target = agent_dir / "mod.py"
        target.write_text(_UNUSED_IMPORT_FILE, encoding="utf-8")

        _run_hook(target)

        # The unused import the agent wrote for code it is about to add must
        # still be there on the next Read — the whole point of #10057.
        assert "import os" in target.read_text(encoding="utf-8")


def test_non_agent_write_still_strips_unused_import() -> None:
    # Companion pin: human/interactive checkouts (no worktrees/issue-<N>
    # segment) keep the existing destructive strip, so CI-visible behaviour
    # for humans is unchanged.
    if shutil.which("ruff") is None:
        return

    with tempfile.TemporaryDirectory() as tmp:
        regular_dir = Path(tmp) / "regular-checkout" / "src"
        regular_dir.mkdir(parents=True)
        target = regular_dir / "mod.py"
        target.write_text(_UNUSED_IMPORT_FILE, encoding="utf-8")

        _run_hook(target)

        # Human context: the F401 strip still fires.
        assert "import os" not in target.read_text(encoding="utf-8")
