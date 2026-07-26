"""Regression test for issue #10577.

Bug: resolving an escape did NOT close its escape-ledger HITL issue.
``EscapeLedgerLoop._surface_findings`` filed a ``hydraflow-find`` /
``escape-ledger`` issue via ``PRPort.create_issue`` (which RETURNS the new
issue number) and discarded the number — the only thing persisted was the
reason-scoped dedup fingerprint (``surfaced:<reason>:<id>``), a bare string
that maps nothing back to the issue. So once a human recorded a resolution
(``EscapeLedger.append_resolution`` bumps confidence / sets ``encoded_as``),
nothing tied the answered ledger row back to the open GitHub issue, and the
HITL surface was stranded open forever.

Fix: persist the filed issue number per surfacing fingerprint in an
append-only sidecar (``escape.surfaces``), and add a reconcile pass to
``EscapeLedgerLoop`` that — on every enabled tick, BEFORE the
``no_new_commits`` early exit — comments on and closes the issue for any open
link whose ledger row is now answered.

These tests assert the CORRECT (post-fix) behaviour and are GREEN once the fix
lands.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from escape.ledger import EscapeLedger
from escape.models import EscapeRecord
from escape_ledger_loop import (
    SURFACE_REASON_AGING,
    SURFACE_REASON_LOW_CONFIDENCE,
    EscapeLedgerLoop,
    surfacing_fingerprint,
)
from mockworld.fakes.fake_github import FakeGitHub
from tests.helpers import make_bg_loop_deps


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
    state.set_escape_ledger_last_processed_sha.side_effect = lambda sha: cursor.update(
        sha=sha
    )
    state._cursor = cursor
    return state


def _make_dedup() -> MagicMock:
    dedup = MagicMock()
    store: set[str] = set()
    dedup.get.side_effect = lambda: set(store)

    def _set_all(values: set[str]) -> None:
        store.clear()
        store.update(values)

    dedup.set_all.side_effect = _set_all
    dedup._store = store
    return dedup


def _build_loop(
    tmp_path: Path, repo: Path, github: Any, state: MagicMock
) -> EscapeLedgerLoop:
    bg = make_bg_loop_deps(tmp_path)
    object.__setattr__(bg.config, "repo_root", repo)
    object.__setattr__(bg.config, "data_root", tmp_path / "data")
    object.__setattr__(bg.config, "escape_ledger_loop_enabled", True)
    return EscapeLedgerLoop(
        config=bg.config,
        pr_manager=github,
        state=state,
        dedup=_make_dedup(),
        deps=bg.loop_deps,
    )


def _low_conf_aging_record(rid: str = "bug-issue:esc1") -> EscapeRecord:
    # Detected ~5 months before any realistic ``now`` — past the default 14-day
    # aging threshold — with ``low`` confidence and no encoding: eligible for the
    # HITL surface under BOTH the low-confidence and aging reasons.
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


def _issue_number_for_reason(
    data_root: Path, escape_id: str, reason: str
) -> int | None:
    """Scan EVERY JSONL row under *data_root* for a persisted surfacing link.

    The oracle: after surfacing, the filed issue number MUST be attributable to
    the exact ``(escape_id, reason)`` pair somewhere on disk — a bare dedup
    fingerprint string (the pre-fix behaviour) carries no number and fails this.
    """
    fingerprint = surfacing_fingerprint(escape_id, reason)
    for jsonl in data_root.rglob("*.jsonl"):
        for raw_line in jsonl.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            matches_pair = (
                row.get("escape_id") == escape_id and row.get("reason") == reason
            )
            matches_fingerprint = row.get("fingerprint") == fingerprint
            if matches_pair or matches_fingerprint:
                number = row.get("issue_number")
                if isinstance(number, int) and number > 0:
                    return number
    return None


class TestSurfacingPersistsIssueNumber:
    async def test_filed_issue_number_is_attributable_per_reason(
        self, tmp_path: Path
    ) -> None:
        github = FakeGitHub()
        repo = _init_repo(tmp_path)
        loop = _build_loop(tmp_path, repo, github, _make_state(_head(repo)))
        EscapeLedger(loop._ledger_path).append(_low_conf_aging_record())

        filed, _capped = await loop._surface_findings()
        assert filed >= 1

        data_root = Path(loop._config.data_root)
        # BOTH reasons were eligible → both surfaced, each carrying its own number.
        low_num = _issue_number_for_reason(
            data_root, "bug-issue:esc1", SURFACE_REASON_LOW_CONFIDENCE
        )
        aging_num = _issue_number_for_reason(
            data_root, "bug-issue:esc1", SURFACE_REASON_AGING
        )
        assert low_num is not None, "low-confidence surfacing did not persist a number"
        assert aging_num is not None, "aging surfacing did not persist a number"
        # The persisted numbers point at issues the fake actually filed.
        assert await github.get_issue_state(low_num) == "OPEN"
        assert await github.get_issue_state(aging_num) == "OPEN"

    async def test_create_issue_zero_return_persists_no_link(
        self, tmp_path: Path
    ) -> None:
        # A silent create failure (0) must NOT strand a number-less link claiming
        # an issue was filed.
        github = FakeGitHub()

        async def _fail(*_a: Any, **_k: Any) -> int:
            return 0

        object.__setattr__(github, "create_issue", _fail)
        repo = _init_repo(tmp_path)
        loop = _build_loop(tmp_path, repo, github, _make_state(_head(repo)))
        EscapeLedger(loop._ledger_path).append(_low_conf_aging_record())

        await loop._surface_findings()

        data_root = Path(loop._config.data_root)
        assert (
            _issue_number_for_reason(
                data_root, "bug-issue:esc1", SURFACE_REASON_LOW_CONFIDENCE
            )
            is None
        )


class TestResolutionClosesHitlIssue:
    async def test_resolved_escape_issue_is_commented_and_closed(
        self, tmp_path: Path
    ) -> None:
        github = FakeGitHub()
        repo = _init_repo(tmp_path)
        loop = _build_loop(tmp_path, repo, github, _make_state(_head(repo)))
        ledger = EscapeLedger(loop._ledger_path)
        ledger.append(_low_conf_aging_record())

        await loop._surface_findings()
        data_root = Path(loop._config.data_root)
        low_num = _issue_number_for_reason(
            data_root, "bug-issue:esc1", SURFACE_REASON_LOW_CONFIDENCE
        )
        aging_num = _issue_number_for_reason(
            data_root, "bug-issue:esc1", SURFACE_REASON_AGING
        )
        assert low_num is not None
        assert aging_num is not None
        assert await github.get_issue_state(low_num) == "OPEN"
        assert await github.get_issue_state(aging_num) == "OPEN"

        # Human records a resolution: bumps confidence off ``low`` and names an
        # encoding — answers BOTH the low-confidence and aging surfaces.
        ledger.append_resolution(
            "bug-issue:esc1",
            encoded_as="detector",
            attribution_confidence="high",
            notes="confirmed + encoded as detector",
        )

        # A QUIET tick (cursor == HEAD → no_new_commits) must STILL close the
        # stranded issues: the reconcile pass runs before the early exit.
        result = await loop._do_work()
        assert result is not None
        assert result["status"] == "no_new_commits"
        assert result["closed"] == 2

        # No stale HITL surface remains for either reason.
        assert github._issues[low_num].state == "closed"
        assert github._issues[aging_num].state == "closed"
        # The close comment records the resolution: the aging surface names the
        # encoding, the low-confidence surface names the confirmed confidence.
        assert any("detector" in str(c) for c in github._issues[aging_num].comments)
        assert any("high" in str(c) for c in github._issues[low_num].comments)

    async def test_close_is_one_shot_no_recomment_next_tick(
        self, tmp_path: Path
    ) -> None:
        github = FakeGitHub()
        repo = _init_repo(tmp_path)
        loop = _build_loop(tmp_path, repo, github, _make_state(_head(repo)))
        ledger = EscapeLedger(loop._ledger_path)
        ledger.append(_low_conf_aging_record())
        await loop._surface_findings()
        low_num = _issue_number_for_reason(
            Path(loop._config.data_root),
            "bug-issue:esc1",
            SURFACE_REASON_LOW_CONFIDENCE,
        )
        assert low_num is not None
        ledger.append_resolution(
            "bug-issue:esc1", encoded_as="detector", attribution_confidence="high"
        )

        first = await loop._do_work()
        assert first["closed"] >= 1
        comments_after_close = len(github._issues[low_num].comments)

        second = await loop._do_work()
        assert second["closed"] == 0
        # Terminal: no further GitHub work for an already-closed link.
        assert len(github._issues[low_num].comments) == comments_after_close

    async def test_unresolved_escape_issue_stays_open(self, tmp_path: Path) -> None:
        github = FakeGitHub()
        repo = _init_repo(tmp_path)
        loop = _build_loop(tmp_path, repo, github, _make_state(_head(repo)))
        EscapeLedger(loop._ledger_path).append(_low_conf_aging_record())
        await loop._surface_findings()
        low_num = _issue_number_for_reason(
            Path(loop._config.data_root),
            "bug-issue:esc1",
            SURFACE_REASON_LOW_CONFIDENCE,
        )
        assert low_num is not None

        # No resolution recorded → the row is still low-confidence + none-yet.
        result = await loop._do_work()
        assert result["closed"] == 0
        assert await github.get_issue_state(low_num) == "OPEN"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
