"""Regression #11160: a stranded `regression-pin` AGING surface must retire
via the #11161 reconcile mechanism too — not just `bug-issue` escapes.

The live escape ``regression-pin:ee56677201303fa4de5b1dec341447d4a12076d4``
is a ``detection_source="regression-pin"`` row: the DETECTING commit adds its
own ``tests/regressions/`` pin alongside the fix (self-referential), so
``EscapeAutoDiagnoser._trace_commit`` resolves it through the ``added_pin``
branch (``attribution.adds_regression_pin(commit.added_paths)``) — a
different code path from ``test_issue_11161.py``'s covered scenario, where
the pin lives in an EARLIER commit and is found only via
``regression_hits``' ``git grep``. Both #11160 and #11161 aged into an OPEN
HITL issue before the #11161 diagnoser widening existed, so both need
``_reconcile_surfaced_issues`` -> ``_diagnose_open_links`` to retire an
ALREADY-surfaced (spent-fingerprint) link — the widened ``_auto_diagnose``
reason filter alone only helps escapes not yet surfaced.

This test exists to verify — with a real git repo, no pinned diagnosis
inputs — that the generic mechanism #11161 shipped actually covers the
``added_pin`` branch end-to-end, since that branch had no prior test
coverage through the reconcile path.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from escape.ledger import EscapeLedger  # noqa: E402
from escape.models import EscapeRecord  # noqa: E402
from escape.surfaces import SurfacedIssueLedger  # noqa: E402
from escape_ledger_loop import SURFACE_REASON_AGING, EscapeLedgerLoop  # noqa: E402
from mockworld.fakes.fake_github import FakeGitHub  # noqa: E402


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@e.dev")
    _git(repo, "config", "user.name", "t")
    _git(repo, "commit", "-q", "-m", "init", "--allow-empty")
    return repo


def _head(repo: Path) -> str:
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def _make_state(initial_sha: str) -> MagicMock:
    state = MagicMock()
    cursor = {"sha": initial_sha}
    state.get_escape_ledger_last_processed_sha.side_effect = lambda: cursor["sha"]
    state.set_escape_ledger_last_processed_sha.side_effect = lambda sha: (
        cursor.__setitem__("sha", sha)
    )
    return state


def _make_dedup() -> MagicMock:
    dedup = MagicMock()
    store: set[str] = set()
    dedup.get.side_effect = lambda: set(store)
    dedup.set_all.side_effect = lambda values: (store.clear(), store.update(values))
    return dedup


def _build_loop(
    tmp_path: Path,
    repo: Path,
    github: FakeGitHub,
    state: MagicMock,
    *,
    auto_diagnose: bool,
) -> EscapeLedgerLoop:
    from tests.helpers import make_bg_loop_deps

    bg = make_bg_loop_deps(tmp_path)
    object.__setattr__(bg.config, "repo_root", repo)
    object.__setattr__(bg.config, "data_root", tmp_path / "data")
    object.__setattr__(bg.config, "escape_ledger_loop_enabled", True)
    object.__setattr__(bg.config, "escape_ledger_auto_diagnose_enabled", auto_diagnose)
    return EscapeLedgerLoop(
        config=bg.config,
        pr_manager=github,
        state=state,
        dedup=_make_dedup(),
        deps=bg.loop_deps,
    )


async def test_already_surfaced_regression_pin_aging_escape_is_retired_via_reconcile(
    tmp_path: Path,
) -> None:
    """The live escape `ee56677201303fa4de5b1dec341447d4a12076d4`: a
    `regression-pin` row whose fix commit added its OWN pin (`added_pin`
    branch, not `regression_hits` git grep). Its AGING issue was already OPEN
    (filed before the #11161 diagnoser widening), so its
    `surfaced:aging:<id>` fingerprint was already spent — the widened reason
    filter alone cannot retire it; only `_reconcile_surfaced_issues`
    diagnosing the escape behind the already-OPEN link can.
    """
    repo = _init_repo(tmp_path)
    # One commit both fixes the bug AND adds its own regression pin —
    # detect.py would classify this as detection_source="regression-pin"
    # (precedence: revert > regression-pin > hotfix > bug-issue).
    (repo / "src" / "crash.py").write_text("def crash():\n    return 1\n")
    reg = repo / "tests" / "regressions"
    reg.mkdir(parents=True)
    # No literal issue-number text in the pin body: regression_hits' git-grep
    # fallback must NOT be able to find this file too, or a broken added_pin
    # detection could still pass via the fallback (the branch this test exists
    # to isolate).
    (reg / "test_issue_555.py").write_text("def test_bug():\n    pass\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fix: resolve crash (fixes #555)")
    fix_sha = _head(repo)

    github = FakeGitHub()
    state = _make_state(fix_sha)
    escape_id = f"regression-pin:{fix_sha}"
    old = (datetime.now(UTC) - timedelta(days=30)).isoformat()

    # First tick: auto-diagnose OFF — files the AGING surface unconditionally,
    # reproducing the spent-fingerprint / already-open-issue precondition the
    # live escape was actually in.
    loop = _build_loop(tmp_path, repo, github, state, auto_diagnose=False)
    EscapeLedger(loop._ledger_path).append(
        EscapeRecord(
            id=escape_id,
            detected_at=old,
            detection_source="regression-pin",
            detection_ref=fix_sha,
            originating_pr=555,
            originating_merge_sha="",
            merged_at="",
            time_to_detection_hours=None,
            attribution_method="regression-pin",
            attribution_confidence="medium",  # AGING-eligible only
            encoded_as="none-yet",
            notes="Fix commit closing #555 shipped its own regression pin.",
        )
    )
    filed, _capped = await loop._surface_findings()
    assert filed == 1
    (link,) = SurfacedIssueLedger(loop._surfaces_path).open_links()
    assert link.reason == SURFACE_REASON_AGING
    assert await github.get_issue_state(link.issue_number) == "OPEN"

    # Second tick: auto-diagnose ON (this fix deployed) — a quiet tick with no
    # new commits, driving only the reconcile pass.
    loop2 = _build_loop(tmp_path, repo, github, state, auto_diagnose=True)
    result = await loop2._do_work()

    assert result["status"] == "no_new_commits"
    assert result["closed"] == 1, (
        "the already-open regression-pin aging issue must be retired via the "
        "added_pin branch even though its surfacing fingerprint was already "
        "spent before auto-diagnose ran"
    )
    assert github._issues[link.issue_number].state == "closed"
    resolved = EscapeLedger(loop2._ledger_path).read_latest_index()[escape_id]
    assert resolved.attribution_confidence == "high"
    assert resolved.encoded_as == "regression-test"
