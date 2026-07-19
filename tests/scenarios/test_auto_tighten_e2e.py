"""End-to-end test for AutoTightenLoop's PR-actuation path (Task 15).

This is the sibling e2e to ``tests/scenarios/test_adr_conformance_e2e.py``:
real I/O, no mocks-of-mocks, except at the true network boundary (``gh``).

The specific risk this test exists to close: ``TighteningPrAuthor.open()``
writes the rendered ``FileEdit``s to ``repo_root`` (see
``auto_tighten/pr_author.py``), then calls the REAL
``open_automated_pr_async`` (``src/auto_pr.py``). That helper creates a
SEPARATE ephemeral worktree via ``git worktree add -b <branch> <path>
origin/<base>`` and stages/commits FROM THERE, not from ``repo_root``. It
copies each file by ``path.relative_to(repo_root)`` into the new worktree
before ``git add``. Every existing unit/scenario test fakes ``pr_author``
wholesale (``AsyncMock``), so this copy-into-worktree link has never been
exercised against real git. If it were broken, the resulting PR branch
would carry an empty (or missing) diff and the ratchet would silently never
actually tighten in production despite reporting ``tightened == 1``.

Repo/origin setup mirrors ``tests/test_auto_pr.py``'s ``bare_remote`` /
``local_repo`` fixtures: a bare ``origin`` repo plus a clone with the base
branch (here ``staging``, matching ``config.base_branch()`` under
ADR-0042) pushed up, since ``open_automated_pr_async`` fetches and branches
off ``origin/{base}``.

Only ``gh`` is stubbed, keyed off ``cmd[0] == "gh"`` in a fake
``subprocess_util.run_subprocess`` matching its real async signature
(``*cmd, cwd=None, gh_token="", timeout=120.0, runner=None``); every ``git``
call is delegated to the ORIGINAL ``run_subprocess`` (captured before
monkeypatching) so real git executes for real, including the
worktree-add/copy/stage/commit/push sequence under test.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

import subprocess_util
from auto_tighten.attribution import AttributionResolver
from auto_tighten.coverage_adapter import CoverageAdapter
from auto_tighten.coverage_ingestor import CoverageIngestor
from auto_tighten.models import CoverageRecord, Observation
from auto_tighten.observation_store import ObservationStore
from auto_tighten.pr_author import TighteningPrAuthor
from auto_tighten_loop import AutoTightenLoop
from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus

pytestmark = pytest.mark.scenario_loops

_STABILITY_TICKS = 3
_MARGIN = 1.0
_BASELINE = 70.0
# weakest([78.0, 78.5, 79.0]) == 78.0; apply_margin -> 78.0 - 1.0 == 77.0
_EXPECTED_FLOOR = 77.0


def _seed_coverage_jsonl(path: Path, percents: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        CoverageRecord(
            timestamp=f"2026-07-0{i + 1}T00:00:00Z",
            coverage_percent=pct,
            commit_sha=f"sha{i}",
            run_id=str(i),
        ).model_dump_json()
        for i, pct in enumerate(percents)
    ]
    path.write_text("\n".join(lines) + "\n")


def _init_repo_with_staging_base(tmp_path: Path) -> tuple[Path, Path]:
    """Build a real bare ``origin`` + a local clone with ``staging`` pushed.

    Mirrors ``tests/test_auto_pr.py``'s ``bare_remote``/``local_repo``
    fixtures (inlined here rather than imported, since those are
    function-scoped fixtures in another test module). ``open_automated_pr_async``
    does ``git fetch origin {base}`` then ``git worktree add -b <branch>
    <path> origin/{base}``, so a real bare remote is required — a single
    local repo with no ``origin`` remote would fail at the worktree-add step.

    Returns ``(local_repo, bare_remote)``.
    """
    bare_remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(bare_remote)], check=True)

    local = tmp_path / "repo"
    subprocess.run(["git", "clone", str(bare_remote), str(local)], check=True)
    subprocess.run(["git", "-C", str(local), "checkout", "-b", "staging"], check=True)
    # Repo-local identity (not global) so worktrees created from this repo's
    # shared git dir inherit it — CI runners have no global git config.
    subprocess.run(["git", "-C", str(local), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(local), "config", "user.name", "t"], check=True)

    (local / "pyproject.toml").write_text(
        f"[tool.coverage.report]\nfail_under = {int(_BASELINE)}\nshow_missing = true\n"
    )
    src_dir = local / "src"
    src_dir.mkdir()
    (src_dir / "trivial.py").write_text("def add(a, b):\n    return a + b\n")

    subprocess.run(["git", "-C", str(local), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(local), "commit", "-m", "init"], check=True)
    subprocess.run(
        ["git", "-C", str(local), "push", "-u", "origin", "staging"], check=True
    )
    return local, bare_remote


def _build_stub_run_subprocess(gh_calls: list[tuple[str, ...]]):
    """Fake ``subprocess_util.run_subprocess`` matching the real signature.

    ``git`` commands are delegated to the ORIGINAL (pre-monkeypatch)
    ``run_subprocess`` so real git executes end to end (worktree add, file
    staging, commit, push). ``gh`` commands are captured into ``gh_calls``
    and answered with a canned success WITHOUT shelling out.
    """
    original_run_subprocess = subprocess_util.run_subprocess

    async def fake_run_subprocess(
        *cmd: str,
        cwd: Path | None = None,
        gh_token: str = "",
        timeout: float = 120.0,
        runner: object = None,
    ) -> str:
        if cmd and cmd[0] == "git":
            return await original_run_subprocess(
                *cmd, cwd=cwd, gh_token=gh_token, timeout=timeout, runner=runner
            )
        if cmd and cmd[0] == "gh":
            gh_calls.append(cmd)
            if cmd[1:3] == ("pr", "create"):
                return "https://github.com/hydra/hydraflow/pull/999\n"
            return ""
        raise AssertionError(f"unexpected non-git/gh command in stub: {cmd!r}")

    return fake_run_subprocess, original_run_subprocess


async def test_auto_tighten_e2e_pr_actuation(tmp_path, monkeypatch) -> None:
    """A stable, attributed coverage gain writes a REAL PR branch with the
    bumped ``fail_under`` actually committed by ``open_automated_pr_async``'s
    separate worktree — not just present (unstaged) in ``repo_root``.

    Asserts:
    1. A branch matching ``auto-tighten/coverage-*`` exists — pushed to the
       real ``origin`` remote (``open_automated_pr_async``'s cleanup always
       deletes the local branch ref in ``repo_root``, so ``origin`` is the
       surviving copy — see the assertion's inline comment for detail).
    2. THE CRITICAL ONE: that branch's committed tree contains
       ``pyproject.toml`` with ``fail_under`` raised to 77 (not 70) — proven
       via a real ``git show <branch>:pyproject.toml`` against ``origin``,
       run with the saved ORIGINAL ``run_subprocess`` directly (not through
       the loop).
    3. ``gh pr create`` was invoked with ``--base staging`` (this test's
       ``config.base_branch()``), and ``gh pr merge --auto`` was attempted.
    4. ``_do_work()``'s result has ``tightened == 1``.
    """
    repo_root, bare_remote = _init_repo_with_staging_base(tmp_path)

    config = HydraFlowConfig(
        data_root=tmp_path / ".hydraflow-data",
        repo="hydra/hydraflow",
        repo_root=repo_root,
        auto_tighten_loop_enabled=True,
        auto_tighten_stability_ticks=_STABILITY_TICKS,
        auto_tighten_coverage_margin=_MARGIN,
        staging_enabled=True,
    )
    assert config.base_branch() == "staging"

    cov_path = config.repo_data_root / "metrics" / "coverage.jsonl"
    _seed_coverage_jsonl(cov_path, [78.0, 78.5, 79.0])

    obs_store = ObservationStore(config.repo_data_root / "metrics" / "tighten.jsonl")
    # Pre-seed one tick short of stability so the single _do_work() call
    # supplies the confirming tick (mirrors test_auto_tighten_loop.py and
    # test_auto_tighten_scenario.py's fixture pattern).
    for pct in [78.0, 78.5]:
        obs_store.append(
            Observation(
                ts="2026-07-01T00:00:00Z",
                ratchet_id="coverage",
                current=pct,
                baseline=_BASELINE,
                direction="tighter",
            )
        )

    adapter = CoverageAdapter(coverage_jsonl=cov_path, margin=_MARGIN)
    ingestor = CoverageIngestor(cov_path, fetch_latest=lambda: None)
    attribution = AttributionResolver(
        list_merged_prs=lambda since: [{"number": 11, "files": ["tests/test_x.py"]}]
    )
    # REAL TighteningPrAuthor / REAL open_automated_pr_async — this is the
    # actuation path under test, matching service_registry.py's production
    # wiring: TighteningPrAuthor(repo_root=config.repo_root, base=config.base_branch()).
    pr_author = TighteningPrAuthor(
        repo_root=config.repo_root, base=config.base_branch()
    )

    bus = EventBus()
    deps = LoopDeps(
        event_bus=bus,
        stop_event=asyncio.Event(),
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )

    loop = AutoTightenLoop(
        config=config,
        state=None,
        deps=deps,
        adapters=[adapter],
        ingestor=ingestor,
        attribution=attribution,
        pr_author=pr_author,
        observation_store=obs_store,
    )

    gh_calls: list[tuple[str, ...]] = []
    fake_run_subprocess, original_run_subprocess = _build_stub_run_subprocess(gh_calls)
    monkeypatch.setattr(subprocess_util, "run_subprocess", fake_run_subprocess)

    result = await loop._do_work()

    assert result["status"] == "ok"
    # ── 4. tightened == 1 ──────────────────────────────────────────────────
    assert result["tightened"] == 1, f"expected exactly one tightening, got {result}"

    # ── 1. A branch matching auto-tighten/coverage-* exists in the real repo ─
    # open_automated_pr_async's `finally` always removes the ephemeral
    # worktree AND deletes the local branch (`git branch -D`) regardless of
    # outcome — see auto_pr.py::_remove_worktree_async — so the branch only
    # survives on the `origin` remote it was pushed to, not as a local ref
    # in `repo_root`. Check the bare remote instead.
    branch_list = subprocess.run(
        ["git", "-C", str(bare_remote), "branch", "--list", "auto-tighten/coverage-*"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "auto-tighten/coverage-" in branch_list, (
        f"expected an auto-tighten/coverage-* branch on origin, got: {branch_list!r}"
    )
    branch_name = branch_list.strip().lstrip("* ").strip()
    assert branch_name == f"auto-tighten/coverage-{_EXPECTED_FLOOR:.1f}"

    # ── 3. gh pr create used --base staging; gh pr merge --auto attempted ───
    create_calls = [c for c in gh_calls if c[1:3] == ("pr", "create")]
    assert len(create_calls) == 1, f"expected exactly one gh pr create, got {gh_calls}"
    create_cmd = create_calls[0]
    assert "--base" in create_cmd
    base_idx = create_cmd.index("--base")
    assert create_cmd[base_idx + 1] == "staging"

    merge_calls = [c for c in gh_calls if c[1:3] == ("pr", "merge")]
    assert len(merge_calls) == 1, (
        f"expected exactly one gh pr merge --auto, got {gh_calls}"
    )
    assert "--auto" in merge_calls[0]

    # ── 2. THE CRITICAL ONE: the branch's committed tree actually contains
    # the bumped fail_under — proves file edits written to repo_root reached
    # the SEPARATE worktree open_automated_pr_async committed from. Uses the
    # saved ORIGINAL run_subprocess directly (real git), not through the loop.
    # Read straight off the bare remote (`git show` works against any git
    # repo, bare or not — no local branch ref is needed in `repo_root` since
    # cleanup deletes it there).
    committed_pyproject = await original_run_subprocess(
        "git", "show", f"{branch_name}:pyproject.toml", cwd=bare_remote
    )
    expected_floor_int = int(_EXPECTED_FLOOR)
    assert f"fail_under = {expected_floor_int}" in committed_pyproject, (
        "the auto-tighten branch's committed pyproject.toml does NOT contain "
        f"the bumped fail_under; actual content:\n{committed_pyproject}"
    )
    assert f"fail_under = {int(_BASELINE)}" not in committed_pyproject
