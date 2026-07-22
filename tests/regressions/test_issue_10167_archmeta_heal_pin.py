"""Regression test for #10167 — arch-stale heal must pin ``.meta.json`` to base.

Bug: ``docs/arch/.meta.json`` is ``merge=arch-meta`` in ``.gitattributes`` — a
CUSTOM git merge driver (``cp %B %A`` = take incoming/base) registered only in
local git config. It resolves cleanly LOCALLY, but **GitHub cannot run custom
merge drivers server-side**. So every ``staging`` advance that touches
``.meta.json`` (essentially every merge — it is the arch runner's per-commit
"volatile stamp" sink) marks every open PR DIRTY.

The automated arch-stale heal in ``DependabotMergeLoop``
(``refresh_pr_branch_with_arch_regen`` → ``auto_pr.refresh_branch_with_arch_
regen``) merged base + ran ``arch.runner --emit`` + committed + pushed. But
``arch.runner`` REGENERATES ``.meta.json`` branch-specifically (``ours != base``),
which re-arms the server-side conflict on the NEXT staging advance → the healed
PR re-DIRTYies → endless heal toil (the single biggest source of heal toil in
the 2026-07-21 board-drain session).

Fix (#10167, option 1): after ``arch.runner --emit`` and before the heal commit,
restore the BASE branch's ``.meta.json`` (``git checkout origin/<base> --
docs/arch/.meta.json``). The committed ``.meta.json`` then equals ``base``, so
GitHub's next 3-way merge sees ``ours == merge-base`` → no conflict → the healed
PR stops re-DIRTYing. ``.meta.json`` is exempt from arch-drift checks
(arch.runner ignores it; ``test_curated_drift`` skips it), so keeping base's
copy is CI-safe.

This test pins the correct post-fix behavior: the committed ``.meta.json``
equals the base branch's copy — NOT the branch-specific regen — while the
generated artifacts ARE the fresh regen.
"""

from __future__ import annotations

import subprocess
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest


@pytest.fixture
def bare_remote(tmp_path: Path) -> Path:
    """A bare git repo that acts as 'origin' for the heal's push."""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True)
    return remote


@pytest.fixture
def local_repo(tmp_path: Path, bare_remote: Path) -> Path:
    """A checkout of the bare remote with one initial commit on ``main``."""
    local = tmp_path / "local"
    subprocess.run(["git", "clone", str(bare_remote), str(local)], check=True)
    subprocess.run(["git", "-C", str(local), "checkout", "-b", "main"], check=True)
    subprocess.run(["git", "-C", str(local), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(local), "config", "user.name", "t"], check=True)
    (local / "README.md").write_text("init\n")
    subprocess.run(["git", "-C", str(local), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(local), "commit", "-m", "init"], check=True)
    subprocess.run(
        ["git", "-C", str(local), "push", "-u", "origin", "main"], check=True
    )
    return local


def _seed(local_repo: Path, *, bot_branch: str, base: str = "staging") -> None:
    """Seed a base branch and a bot branch that BOTH conflict on the generated
    artifact AND on ``docs/arch/.meta.json`` — the #10167 heal scenario."""
    arch = local_repo / "docs" / "arch"
    gen = arch / "generated"
    gen.mkdir(parents=True, exist_ok=True)
    meta = arch / ".meta.json"

    def _git(*args: str) -> None:
        subprocess.run(["git", "-C", str(local_repo), *args], check=True)

    (gen / "x.md").write_text("base v0\n")
    meta.write_text('{"stamp": "seed"}\n')
    _git("add", "-A")
    _git("commit", "-m", "seed arch files")
    _git("push", "origin", "main")

    # base advances both files.
    _git("checkout", "-b", base)
    (gen / "x.md").write_text("BASE ADVANCED\n")
    meta.write_text('{"stamp": "BASE"}\n')
    _git("add", "-A")
    _git("commit", "-m", f"advance {base}")
    _git("push", "-u", "origin", base)

    # bot branch (off the seed) edits both files differently → merge conflict.
    _git("checkout", "-b", bot_branch, "main")
    (gen / "x.md").write_text("BOT STALE\n")
    meta.write_text('{"stamp": "BOT"}\n')
    _git("add", "-A")
    _git("commit", "-m", "bot edit")
    _git("push", "-u", "origin", bot_branch)
    _git("checkout", "main")


def _regen_stub() -> Callable[..., Awaitable[str]]:
    """Fake ``run_subprocess``: real git, but intercept ``arch.runner --emit`` to
    write the regenerated generated artifact AND a branch-specific
    ``.meta.json`` — the exact regen that re-arms the conflict absent the pin."""

    async def fake_run(
        *cmd: str,
        cwd: Path | None = None,
        gh_token: str = "",
        timeout: float = 120.0,
        runner: object = None,
    ) -> str:
        del gh_token, timeout, runner
        if "arch.runner" in cmd:
            assert cwd is not None
            gen = Path(cwd) / "docs" / "arch" / "generated" / "x.md"
            gen.parent.mkdir(parents=True, exist_ok=True)
            gen.write_text("REGENERATED FROM SOURCE\n")
            (Path(cwd) / "docs" / "arch" / ".meta.json").write_text(
                '{"stamp": "BRANCH_SPECIFIC_REGEN"}\n'
            )
            return ""
        try:
            return subprocess.run(
                list(cmd),
                cwd=str(cwd) if cwd is not None else None,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(exc.stderr or str(exc)) from exc

    return fake_run


@pytest.mark.asyncio
async def test_arch_heal_pins_meta_json_to_base(
    local_repo: Path, bare_remote: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from auto_pr import refresh_branch_with_arch_regen

    _seed(local_repo, bot_branch="ul-edge-10167", base="staging")
    monkeypatch.setattr("subprocess_util.run_subprocess", _regen_stub())

    result = await refresh_branch_with_arch_regen(
        repo_root=local_repo,
        branch="ul-edge-10167",
        base="staging",
        commit_author_name="t",
        commit_author_email="t@t",
    )

    assert result.status == "refreshed", result.error

    def _show(ref: str, path: str) -> str:
        return subprocess.run(
            ["git", "-C", str(bare_remote), "show", f"{ref}:{path}"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    committed_meta = _show("ul-edge-10167", "docs/arch/.meta.json")
    # The healed PR's committed .meta.json == the base branch's copy: this is
    # what makes GitHub's next 3-way merge see ours == merge-base (no conflict).
    assert committed_meta == _show("staging", "docs/arch/.meta.json")
    assert '"BASE"' in committed_meta
    # It is NOT the branch-specific regen stamp (that re-arms the conflict).
    assert "BRANCH_SPECIFIC_REGEN" not in committed_meta
    # The real generated artifacts ARE the fresh regen (heal still works).
    assert "REGENERATED FROM SOURCE" in _show(
        "ul-edge-10167", "docs/arch/generated/x.md"
    )
