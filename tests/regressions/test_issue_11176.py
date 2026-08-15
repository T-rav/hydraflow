"""Regression test for issue #11176.

Bug: ``EscapeLedgerLoop._surface_findings`` applied the per-tick ask-budget
cap (``escape_ledger_max_issues_per_tick``) BEFORE running auto-diagnose. On a
busy tick — more eligible (low-confidence + aging) findings than the ask
budget — any eligible finding ranked past the cap boundary was silently
dropped by the cap and NEVER reached the diagnoser. A machine-resolvable
AGING escape ranked past the cap therefore never got a chance to self-resolve:
it just kept aging past the encoding threshold, tick after tick — exactly the
live symptom this issue reports for escape ``055267e7b2b7``
(``regression-pin:055267e7b2b7900d615b0ff8553ef511dc3e8652``).

Fix: diagnose runs over the FULL uncapped eligible set first
(``eligible_findings``); only the residue auto-diagnose could not resolve or
dismiss is capped for human filing (``apply_ask_budget``). A diagnosable
escape self-answers regardless of how many OTHER findings are competing for
the ask budget that tick.
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
from escape_ledger_loop import EscapeLedgerLoop  # noqa: E402
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


def _make_dedup() -> MagicMock:
    dedup = MagicMock()
    store: set[str] = set()
    dedup.get.side_effect = lambda: set(store)
    dedup.set_all.side_effect = lambda values: (store.clear(), store.update(values))
    return dedup


def _build_loop(tmp_path: Path, repo: Path, github: FakeGitHub) -> EscapeLedgerLoop:
    from tests.helpers import make_bg_loop_deps

    bg = make_bg_loop_deps(tmp_path)
    object.__setattr__(bg.config, "repo_root", repo)
    object.__setattr__(bg.config, "data_root", tmp_path / "data")
    object.__setattr__(bg.config, "escape_ledger_loop_enabled", True)
    object.__setattr__(bg.config, "escape_ledger_auto_diagnose_enabled", True)
    return EscapeLedgerLoop(
        config=bg.config,
        pr_manager=github,
        state=MagicMock(),
        dedup=_make_dedup(),
        deps=bg.loop_deps,
    )


def _low_confidence_record(rid: str) -> EscapeRecord:
    """Eligible only for SURFACE_REASON_LOW_CONFIDENCE, never diagnosable (no
    matching commit, no referenced issue) — stays INCONCLUSIVE."""
    return EscapeRecord(
        id=rid,
        detected_at=datetime.now(UTC).isoformat(),  # fresh: not aging-eligible
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


async def test_aging_resolvable_escape_self_answers_despite_a_busy_ask_budget(
    tmp_path: Path,
) -> None:
    github = FakeGitHub()
    repo = _init_repo(tmp_path)

    # A regression pin lands, then the fix commit that (mechanically) detects
    # the escape — the pin is reachable via `regression_hits`' git grep, so
    # auto-diagnose CAN self-resolve this row once it actually runs on it.
    reg = repo / "tests" / "regressions"
    reg.mkdir(parents=True)
    (reg / "test_bug_5527.py").write_text(
        "# regression pin for #5527\ndef test_bug(): pass\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "test: pin regression for #5527")
    (repo / "src" / "adr_citations.py").write_text("def parse():\n    return 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fix: resolve drift parse (fixes #5527)")
    fix_sha = _head(repo)

    loop = _build_loop(tmp_path, repo, github)
    ledger = EscapeLedger(loop._ledger_path)

    # 3 unrelated low-confidence findings — exactly the default
    # `escape_ledger_max_issues_per_tick` worth — compete with the aging
    # finding for the ask budget. Diagnosis runs over the full eligible set,
    # bounded only by `escape_ledger_max_diagnoses_per_tick` (default 25,
    # well above these 4 rows), so a cap-before-diagnose bug would have
    # starved the aging row out of the eligible set entirely, before it ever
    # reached the diagnoser.
    for i in range(3):
        ledger.append(_low_confidence_record(f"bug-issue:noise{i}"))

    aging_id = f"bug-issue:{fix_sha}"
    old = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    ledger.append(
        EscapeRecord(
            id=aging_id,
            detected_at=old,
            detection_source="bug-issue",
            detection_ref=fix_sha,
            originating_pr=5527,
            originating_merge_sha="",
            merged_at="",
            time_to_detection_hours=None,
            attribution_method="fixes-chain",
            attribution_confidence="medium",  # AGING-eligible only
            encoded_as="none-yet",
            notes="",
        )
    )

    filed, capped = await loop._surface_findings()

    # The 3 noise findings still spend the ask budget (INCONCLUSIVE: no
    # regression encoding, no referenced issue to check) ...
    assert filed == 3
    assert capped is False

    # ... but the aging row must have reached the diagnoser DESPITE ranking
    # past the ask budget, and self-resolved without ever asking a human.
    resolved = EscapeLedger(loop._ledger_path).read_latest_index()[aging_id]
    assert resolved.attribution_confidence == "high", (
        "the diagnosable aging escape must self-resolve even when it ranks "
        "past the per-tick ask budget — a cap-before-diagnose bug would "
        "silently drop it from the eligible set and leave it aging forever"
    )
    assert resolved.encoded_as == "regression-test"
    links = SurfacedIssueLedger(loop._surfaces_path).open_links()
    assert aging_id not in {link.escape_id for link in links}, (
        "a self-resolved escape must never have consumed a human-ask slot"
    )
