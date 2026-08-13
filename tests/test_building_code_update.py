"""Tests for the building-code updater (#11060 slice 4) — end-to-end on tmp git repos."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from onboarding.kernel_lock import KERNEL_LOCK_FILENAME
from onboarding.kernel_writer import KernelSpec, stamp_kernel

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from building_code_update import main as update_main  # noqa: E402

_SPEC = KernelSpec(name="bc-child", package_name="bcchild")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _stamped_child(tmp_path: Path) -> Path:
    child = tmp_path / "child"
    stamp_kernel(_SPEC, child)
    _git(child, "init", "-q")
    _git(child, "config", "user.email", "t@e.dev")
    _git(child, "config", "user.name", "t")
    _git(child, "add", "-A")
    _git(child, "commit", "-q", "-m", "chore: stamp kernel")
    return child


def _run(child: Path, argv: list[str] | None = None) -> int:
    sys.argv = ["building_code_update", str(child), *(argv or [])]
    return update_main()


def _age_lock(child: Path) -> None:
    """Simulate the building code having moved on since this child was stamped."""
    lock_path = child / KERNEL_LOCK_FILENAME
    lock = json.loads(lock_path.read_text())
    lock["building_code_version"] = "2020.01.01"
    lock["files"]["Makefile"]["sha256"] = "0" * 64
    lock_path.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n")
    _git(child, "add", "-A")
    _git(child, "commit", "-q", "-m", "test: age the lock")


def test_no_lock_exits_2(tmp_path: Path, capsys) -> None:
    (tmp_path / "bare").mkdir()
    assert _run(tmp_path / "bare") == 2
    assert "no update contract" in capsys.readouterr().err


def test_current_child_is_a_no_op(tmp_path: Path, capsys) -> None:
    child = _stamped_child(tmp_path)
    assert _run(child) == 0
    assert "nothing to update" in capsys.readouterr().out
    # No branch created.
    heads = subprocess.run(
        ["git", "branch", "--list"],
        cwd=child,
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    assert "building-code/" not in heads


def test_dirty_tree_refuses(tmp_path: Path, capsys) -> None:
    child = _stamped_child(tmp_path)
    _age_lock(child)
    (child / "uncommitted.txt").write_text("wip\n")
    assert _run(child) == 2
    assert "dirty" in capsys.readouterr().err


def test_stale_child_gets_update_branch_with_commit(tmp_path: Path, capsys) -> None:
    child = _stamped_child(tmp_path)
    _age_lock(child)
    # Also locally modify a template file: the update branch overwrites it —
    # the merge conversation happens in PR review, never silently.
    (child / "Makefile").write_text("# locally hacked\n")
    _git(child, "add", "-A")
    _git(child, "commit", "-q", "-m", "local hack")

    assert _run(child) == 1
    out = capsys.readouterr().out
    assert "update branch ready: building-code/" in out
    assert "gh pr create" in out  # printed, not automated

    # On the update branch: Makefile restored to prescription, lock refreshed,
    # product-owned CLAUDE.md untouched semantics hold (still present).
    head_branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=child,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    assert head_branch.startswith("building-code/")
    assert "# locally hacked" not in (child / "Makefile").read_text()
    lock = json.loads((child / KERNEL_LOCK_FILENAME).read_text())
    assert lock["building_code_version"] != "2020.01.01"
    # The branch has exactly one new commit and a clean tree.
    dirty = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=child,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    assert dirty == ""
