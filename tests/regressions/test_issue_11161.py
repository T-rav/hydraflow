"""Regression #11161: the AGING escape surface is never machine-diagnosed.

``EscapeLedgerLoop._auto_diagnose`` pre-filtered on
``reason != SURFACE_REASON_LOW_CONFIDENCE``, so an AGING finding (a
``none-yet`` row older than ``escape_ledger_encoding_age_days``) always
skipped the diagnoser and filed a human issue — even when its regression
encoding was already on disk (the live instance: escape ``9196f7403620``,
whose encoding is reachable only through ``auto_diagnose.regression_hits``'
``git grep``, not ``added_paths``). Pins that BOTH surfacing reasons run the
same diagnose pass.

Widening the reason filter alone is NOT enough to retire the live escape,
though: ``select_findings_to_surface`` drops a (record, reason) pair once its
reason-scoped fingerprint is already spent, and ``9196f7403620``'s AGING
fingerprint was spent the moment the pre-#11161 code filed its issue — so
``_surface_findings``'s ``_auto_diagnose`` call never sees that escape again,
no matter how the reason filter is widened. ``test_already_surfaced_aging_escape_is_retired_via_reconcile``
below covers that gap end-to-end over a real git repo (no pinned diagnosis
inputs, no bypassed ``EscapeAutoDiagnoser``/``regression_hits`` git grep).
"""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from escape.auto_diagnose import EscapeDiagnosis  # noqa: E402
from escape.ledger import EscapeLedger  # noqa: E402
from escape.models import EscapeRecord  # noqa: E402
from escape.surfaces import SurfacedIssueLedger  # noqa: E402
from escape_ledger_loop import (
    SURFACE_REASON_AGING,  # noqa: E402
    SURFACE_REASON_LOW_CONFIDENCE,  # noqa: E402
    EscapeLedgerLoop,  # noqa: E402
)
from mockworld.fakes.fake_github import FakeGitHub  # noqa: E402


class _FakeDiagnoser:
    def __init__(self, verdict: EscapeDiagnosis) -> None:
        self.verdict = verdict
        self.calls: list[EscapeRecord] = []

    async def diagnose(self, record: EscapeRecord) -> EscapeDiagnosis:
        self.calls.append(record)
        return self.verdict


def _record(rid: str) -> EscapeRecord:
    return EscapeRecord(
        id=rid,
        detected_at="2026-01-01T00:00:00+00:00",
        detection_source="bug-issue",
        detection_ref=rid.split(":", 1)[-1],
        originating_pr=None,
        originating_merge_sha="",
        merged_at="",
        time_to_detection_hours=None,
        attribution_method="fixes-chain",
        attribution_confidence="low",
        encoded_as="none-yet",
        notes="",
    )


def _loop_with_diagnoser(tmp_path: Path, diagnoser: _FakeDiagnoser) -> EscapeLedgerLoop:
    from tests.helpers import make_bg_loop_deps

    bg = make_bg_loop_deps(tmp_path)
    object.__setattr__(bg.config, "data_root", tmp_path / "data")
    from unittest.mock import MagicMock

    return EscapeLedgerLoop(
        config=bg.config,
        pr_manager=MagicMock(),
        state=MagicMock(),
        dedup=MagicMock(),
        deps=bg.loop_deps,
        auto_diagnoser=diagnoser,  # type: ignore[arg-type]
    )


async def test_aging_reason_reaches_the_diagnoser(tmp_path: Path) -> None:
    diagnoser = _FakeDiagnoser(EscapeDiagnosis.INCONCLUSIVE)
    loop = _loop_with_diagnoser(tmp_path, diagnoser)
    record = _record("bug-issue:aged")

    await loop._auto_diagnose([(record, SURFACE_REASON_AGING)])

    assert diagnoser.calls == [record], (
        "AGING findings must reach the diagnoser exactly like "
        "LOW_CONFIDENCE findings do — no reason pre-filter"
    )


async def test_low_confidence_reason_still_reaches_the_diagnoser(
    tmp_path: Path,
) -> None:
    # Unchanged pre-existing behavior — must not regress alongside the fix.
    diagnoser = _FakeDiagnoser(EscapeDiagnosis.INCONCLUSIVE)
    loop = _loop_with_diagnoser(tmp_path, diagnoser)
    record = _record("bug-issue:live")

    await loop._auto_diagnose([(record, SURFACE_REASON_LOW_CONFIDENCE)])

    assert diagnoser.calls == [record]


async def test_resolved_encoded_verdict_drops_the_aging_finding(
    tmp_path: Path,
) -> None:
    diagnoser = _FakeDiagnoser(EscapeDiagnosis.RESOLVED_ENCODED)
    loop = _loop_with_diagnoser(tmp_path, diagnoser)
    record = _record("bug-issue:aged")

    residue = await loop._auto_diagnose([(record, SURFACE_REASON_AGING)])

    assert residue == [], "a machine-resolved aging finding must not reach a human"


# ---------------------------------------------------------------------------
# End-to-end: an ALREADY-surfaced (spent-fingerprint) aging escape must still
# be retired once auto-diagnose is in play — a real git repo, a real
# EscapeAutoDiagnoser (no pinned diagnosis inputs), and FakeGitHub throughout.
# ---------------------------------------------------------------------------


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


async def test_already_surfaced_aging_escape_is_retired_via_reconcile(
    tmp_path: Path,
) -> None:
    """The live escape `9196f7403620`: its AGING issue was already OPEN
    (filed under the pre-#11161 code) by the time the widened reason filter
    landed, so its ``surfaced:aging:<id>`` fingerprint was already spent.
    ``select_findings_to_surface`` never re-offers a spent fingerprint, so
    ``_surface_findings``'s ``_auto_diagnose`` call can never re-diagnose it —
    the widened reason filter alone cannot retire this issue.
    ``_reconcile_surfaced_issues`` must diagnose the escape behind an
    already-OPEN link directly, so a resolution recorded there closes the
    stranded issue on the same tick.
    """
    repo = _init_repo(tmp_path)
    # A regression pin lands, then the fix commit that (mechanically) detects
    # the escape — the pin is reachable via `regression_hits`' git grep.
    reg = repo / "tests" / "regressions"
    reg.mkdir(parents=True)
    (reg / "test_bug_321.py").write_text(
        "# regression pin for #321\ndef test_bug(): pass\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "test: pin regression for #321")
    (repo / "src" / "crash.py").write_text("def crash():\n    return 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fix: resolve crash (fixes #321)")
    fix_sha = _head(repo)

    github = FakeGitHub()
    state = _make_state(fix_sha)
    escape_id = f"bug-issue:{fix_sha}"
    old = (datetime.now(UTC) - timedelta(days=30)).isoformat()

    # First tick: auto-diagnose OFF — files the AGING surface unconditionally,
    # reproducing the spent-fingerprint / already-open-issue precondition the
    # live escape was actually in.
    loop = _build_loop(tmp_path, repo, github, state, auto_diagnose=False)
    EscapeLedger(loop._ledger_path).append(
        EscapeRecord(
            id=escape_id,
            detected_at=old,
            detection_source="bug-issue",
            detection_ref=fix_sha,
            originating_pr=321,
            originating_merge_sha="",
            merged_at="",
            time_to_detection_hours=None,
            attribution_method="fixes-chain",
            attribution_confidence="medium",  # AGING-eligible only
            encoded_as="none-yet",
            notes="Fix commit closing #321.",
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
        "the already-open aging issue must be retired even though its "
        "surfacing fingerprint was already spent before auto-diagnose ran"
    )
    assert github._issues[link.issue_number].state == "closed"
    resolved = EscapeLedger(loop2._ledger_path).read_latest_index()[escape_id]
    assert resolved.attribution_confidence == "high"
    assert resolved.encoded_as == "regression-test"
