"""Regression guard for #10808 — SampledAuditLoop re-audits its OWN chores.

The silent-escape estimator (``sampled_audit_loop.SampledAuditLoop``, ADR-0029
Pattern B) sampled and adversarially re-reviewed the FACTORY's own
chore/maintenance merges. In one ~5.5h idle window it filed three
``hydraflow-find`` "re-audit disagreement" issues about the factory's own
make-work — ``chore(wiki): maintenance`` (repo_wiki_loop), ``feat(ul):
term-proposer`` (term_proposer_loop), and ``chore(arch): regenerate``
(diagram_loop) merges. That is flux, not signal: the audit's value is
re-reviewing REAL merged product change.

Fix: ``audit.sampling.select_sample`` skips a self-chore merge BEFORE
classification + Bernoulli selection, keyed off the legible module-level
``_SELF_CHORE_SUBJECT_PREFIXES`` (via ``is_self_chore_change``). The loop's SHA
cursor still advances unconditionally, so an excluded change is never revisited.

Guards, pinning the EXACT overnight offenders:

1. **Pure selection** — the three offender subjects are excluded from
   ``select_sample`` even at ``base_rate=1.0``; a substantive ``fix(``/``feat(``
   merge in the same batch is still selected.
2. **Full loop** — over a real git range mixing the offenders with one real
   ``fix(`` merge, the adversarial auditor is spawned ONLY for the real change,
   the chores are never recorded, and the cursor still advances to HEAD.
"""

from __future__ import annotations

import random
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from audit.models import MergedChange
from audit.sampling import is_self_chore_change, select_sample
from audit.store import AuditSampleLedger
from sampled_audit_loop import SampledAuditLoop
from tests.helpers import make_bg_loop_deps

# The exact overnight offenders, plus the two other factory maintenance loops.
_OFFENDER_SUBJECTS = (
    "chore(wiki): maintenance 2026-07-24 (#10461)",
    "feat(ul): term-proposer batch — 3 drafts (#10439)",
    "chore(arch): regenerate architecture knowledge — 2026-07-24 (#10460)",
)
_REAL_SUBJECT = "fix(core): patch an off-by-one in the merge queue (#10462)"

_AGREE = '{"verdict": "agree", "findings": ""}'


def _change(*, pr: int, subject: str) -> MergedChange:
    return MergedChange(
        pr_number=pr,
        merge_sha=f"{pr:040d}",
        subject=subject,
        changed_paths=("src/x.py",),
        merged_at="2026-07-24T00:00:00+00:00",
    )


class TestPureSelectionExcludesOffenders:
    def test_overnight_offenders_are_flagged_self_chore(self) -> None:
        for subject in _OFFENDER_SUBJECTS:
            assert is_self_chore_change(_change(pr=1, subject=subject)), subject

    def test_offenders_never_sampled_but_real_fix_is(self) -> None:
        real = _change(pr=10462, subject=_REAL_SUBJECT)
        batch = [_change(pr=i, subject=s) for i, s in enumerate(_OFFENDER_SUBJECTS)] + [
            real
        ]
        # base_rate 1.0 → every ELIGIBLE change is certain to be selected.
        selected = select_sample(batch, base_rate=1.0, rng=random.Random(0))
        assert [c.id for c in selected] == [real.id]


# --- full-loop end-to-end over a real git range ----------------------------


class _FakeAuditor:
    def __init__(self, response: str) -> None:
        self._response = response
        self.subjects: list[str] = []

    async def audit(self, *, prompt: str) -> str:
        # Record which change was actually re-audited (subject leaks into the
        # prompt) so the test can assert the chores were never spawned.
        self.subjects.append(prompt)
        return self._response


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _head(repo: Path) -> str:
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def _commit(repo: Path, subject: str, path: str) -> None:
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text(f"# {subject}\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", subject)


def _make_state(initial_sha: str) -> MagicMock:
    state = MagicMock()
    store: dict[str, Any] = {"sha": initial_sha, "rate": 1.0, "history": []}
    state.get_sampled_audit_last_processed_sha.side_effect = lambda: store["sha"]
    state.set_sampled_audit_last_processed_sha.side_effect = lambda s: (
        store.__setitem__("sha", s)
    )
    state.get_sampled_audit_governed_rate.side_effect = lambda: store["rate"]
    state.set_sampled_audit_governed_rate.side_effect = lambda r: store.__setitem__(
        "rate", r
    )
    state.get_sampled_audit_disagreement_history.side_effect = lambda: list(
        store["history"]
    )
    state.set_sampled_audit_disagreement_history.side_effect = lambda h: (
        store.__setitem__("history", list(h))
    )
    state._store = store
    return state


def _make_dedup() -> MagicMock:
    dedup = MagicMock()
    store: set[str] = set()
    dedup.get.side_effect = lambda: set(store)
    dedup.set_all.side_effect = lambda v: (store.clear(), store.update(v))
    return dedup


def _make_prs() -> MagicMock:
    prs = MagicMock()
    prs.create_issue = AsyncMock(return_value=500)
    prs.get_issue_state = AsyncMock(return_value="OPEN")
    prs.get_issue_labels = AsyncMock(return_value=[])
    return prs


class TestFullLoopExcludesOffenders:
    async def test_only_the_real_change_is_reaudited(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@e.dev")
        _git(repo, "config", "user.name", "t")
        _git(repo, "commit", "-q", "-m", "init", "--allow-empty")
        base = _head(repo)

        # A realistic idle-window range: three factory self-chores interleaved
        # with one real product fix.
        _commit(repo, _OFFENDER_SUBJECTS[0], "docs/wiki/gotchas.md")
        _commit(repo, _OFFENDER_SUBJECTS[1], "docs/wiki/terms/append.md")
        _commit(repo, _REAL_SUBJECT, "src/merge_queue.py")
        _commit(repo, _OFFENDER_SUBJECTS[2], "docs/arch/generated/loop-registry.md")
        head = _head(repo)

        bg = make_bg_loop_deps(tmp_path)
        object.__setattr__(bg.config, "repo_root", repo)
        object.__setattr__(bg.config, "data_root", tmp_path / "data")
        object.__setattr__(bg.config, "sampled_audit_loop_enabled", True)
        object.__setattr__(bg.config, "sampled_audit_reaudit_enabled", True)
        state = _make_state(initial_sha=base)
        auditor = _FakeAuditor(_AGREE)
        loop = SampledAuditLoop(
            config=bg.config,
            pr_manager=_make_prs(),
            state=state,
            dedup=_make_dedup(),
            deps=bg.loop_deps,
            auditor=auditor,
        )

        result = await loop._do_work()

        # Exactly one change re-audited — the real fix — and it was PR #10462.
        assert result["status"] == "ok"
        assert result["sampled"] == 1
        assert len(auditor.subjects) == 1
        assert "#10462" in auditor.subjects[0]
        # None of the factory self-chores were spawned for re-audit.
        for offender in _OFFENDER_SUBJECTS:
            assert offender not in auditor.subjects[0]

        recorded = AuditSampleLedger(loop._samples_path).read_all()
        assert [s.pr_number for s in recorded] == [10462]

        # The cursor still advances past the whole range, so the excluded
        # self-chores are never re-sampled on a later tick.
        assert state._store["sha"] == head
