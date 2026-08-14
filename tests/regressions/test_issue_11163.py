"""Regression #11163: an unparseable diagnosis row was terminal for
selection but undiagnosed for the verdict lookup — a silent, permanent
escape from every human/aging surface.

``EscapeDiagnosisLedger.terminal_ids()`` used to be ``existing_ids()`` — any
row present in the sidecar counted as terminal, regardless of whether its
``diagnosis`` field parsed into the current ``EscapeDiagnosis`` enum.
``verdict_for()``, separately, validated the diagnosis field and mapped an
unparseable string to ``None`` ("undiagnosed, re-diagnose rather than
guess", #11111). A row written by a newer build (a future enum value) or a
corrupted row therefore satisfied ``terminal_ids()`` — suppressing the
escape from ``EscapeLedgerLoop._surface_findings()`` selection — while
``verdict_for()`` reported it as undiagnosed. No human ever saw it and no
re-diagnosis ever ran: a silent escape, exactly what the sampled re-audit of
PR #11150 (gauntlet) flagged.

The fix routes ``terminal_ids()``, ``verdict_for()``, and
``dismissal_reasons()`` through one shared ``_latest_verdicts()`` map so
they cannot diverge again, and adds ``unreadable_ids()`` so the loop logs a
loud aggregate warning instead of staying silent.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from escape.auto_diagnose import (  # noqa: E402
    EscapeDiagnosis,
    EscapeDiagnosisLedger,
    EscapeDiagnosisRecord,
)
from escape.ledger import EscapeLedger  # noqa: E402
from escape.models import EscapeRecord  # noqa: E402
from escape_ledger_loop import EscapeLedgerLoop  # noqa: E402
from mockworld.fakes.fake_github import FakeGitHub  # noqa: E402

_UNPARSEABLE_DIAGNOSIS = "some-future-verdict"


def test_terminal_ids_and_verdict_for_agree_on_an_unparseable_row(
    tmp_path: Path,
) -> None:
    """The core defect: two readers of the same sidecar row disagreeing.

    Pre-fix, ``terminal_ids()`` (bare row presence) included this id while
    ``verdict_for()`` (validated) reported it undiagnosed. Both must now
    agree: the row is NOT terminal and has NO verdict.
    """
    ledger = EscapeDiagnosisLedger(tmp_path / "d.jsonl")
    ledger.append(
        EscapeDiagnosisRecord(
            escape_id="bug-issue:corrupt",
            diagnosis=_UNPARSEABLE_DIAGNOSIS,
            reason="?",
            decided_at="2026-01-01T00:00:00+00:00",
        )
    )

    assert "bug-issue:corrupt" not in ledger.terminal_ids(), (
        "an unparseable diagnosis row must not silently gate selection as terminal"
    )
    assert ledger.verdict_for("bug-issue:corrupt") is None
    assert ledger.unreadable_ids() == {"bug-issue:corrupt"}, (
        "the divergence must be surfaced, not just silently resolved"
    )


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


def _seed_bug_fix_no_regression(repo: Path, issue: int) -> tuple[str, str]:
    base = _head(repo)
    (repo / "src" / "widget.py").write_text("def widget():\n    return 2\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"fix: repair widget (fixes #{issue})")
    return base, _head(repo)


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


async def test_unparseable_diagnosis_row_does_not_silently_swallow_the_escape(
    tmp_path: Path,
) -> None:
    """End-to-end over a real git repo + FakeGitHub: pre-fix, this escape
    would have been gated out of selection by ``terminal_ids()`` forever,
    with no human issue and no re-diagnosis. Post-fix it must still reach a
    human, and the loop must log the disagreement loudly rather than eat it.
    """
    repo = _init_repo(tmp_path)
    base_sha, head_sha = _seed_bug_fix_no_regression(repo, 11163)
    escape_id = f"bug-issue:{head_sha}"

    github = FakeGitHub()
    state = _make_state(base_sha)
    loop = _build_loop(tmp_path, repo, github, state, auto_diagnose=True)
    EscapeDiagnosisLedger(loop._diagnoses_path).append(
        EscapeDiagnosisRecord(
            escape_id=escape_id,
            diagnosis=_UNPARSEABLE_DIAGNOSIS,
            reason="?",
            decided_at="2026-01-01T00:00:00+00:00",
        )
    )

    logger = logging.getLogger("hydraflow.escape_ledger")
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[method-assign]
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    try:
        result = await loop._do_work()
    finally:
        logger.removeHandler(handler)

    assert result["status"] == "ok"
    assert result["escapes_recorded"] == 1
    assert result["filed"] == 1, (
        "an unparseable diagnosis row must not silently and permanently "
        "suppress the escape from the human surface"
    )
    assert any(
        "unreadable" in rec.getMessage().lower() and escape_id in rec.getMessage()
        for rec in records
    ), "the disagreement must be logged loudly, not resolved in silence"


async def test_terminal_ids_excludes_unparseable_row_when_selecting_findings(
    tmp_path: Path,
) -> None:
    """Narrower unit check on the same selection path #11137 relies on:
    ``_surface_findings`` must treat an unparseable-diagnosis escape as
    eligible, not terminal.
    """
    repo = _init_repo(tmp_path)
    github = FakeGitHub()
    state = _make_state(_head(repo))
    loop = _build_loop(tmp_path, repo, github, state, auto_diagnose=False)

    record = EscapeRecord(
        id="bug-issue:manual",
        detected_at="2026-01-01T00:00:00+00:00",
        detection_source="bug-issue",
        detection_ref="manual",
        originating_pr=None,
        originating_merge_sha="",
        merged_at="",
        time_to_detection_hours=None,
        attribution_method="fixes-chain",
        attribution_confidence="low",
        # encoded_as != "none-yet" so only the low-confidence reason is
        # eligible — isolates the surface under test from the aging one.
        encoded_as="regression-test",
        notes="",
    )
    EscapeLedger(loop._ledger_path).append(record)
    EscapeDiagnosisLedger(loop._diagnoses_path).append(
        EscapeDiagnosisRecord(
            escape_id=record.id,
            diagnosis=_UNPARSEABLE_DIAGNOSIS,
            reason="?",
            decided_at="2026-01-01T00:00:00+00:00",
        )
    )

    filed, capped = await loop._surface_findings()

    assert filed == 1, "unreadable diagnosis must not suppress selection"
    assert capped is False


def test_dismissal_reasons_never_diverges_from_terminal_ids(tmp_path: Path) -> None:
    """All three readers derive from the same map — a DISMISSED verdict
    superseded by an unparseable row must drop out of both views together,
    not leave a stale entry in one and not the other.
    """
    ledger = EscapeDiagnosisLedger(tmp_path / "d.jsonl")
    ledger.append_diagnosis("bug-issue:a", EscapeDiagnosis.DISMISSED, "first")
    ledger.append(
        EscapeDiagnosisRecord(
            escape_id="bug-issue:a",
            diagnosis=_UNPARSEABLE_DIAGNOSIS,
            reason="?",
            decided_at="2026-01-01T00:00:00+00:00",
        )
    )

    assert ledger.dismissal_reasons() == {}
    assert ledger.terminal_ids() == set()
    assert ledger.unreadable_ids() == {"bug-issue:a"}
