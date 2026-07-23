"""Unit tests for SampledAuditLoop (#10370).

Covers the kill-switches, the config_disable air-gap seam (re-audit spawn off),
an end-to-end sample→audit→record over a real merged git commit, the
no-verdict-contamination manifest, the finding-filing budget, the upheld→escape-
ledger cross-link + refuted→false-alarm reconcile, the token-budget cap, the
governed-rate persistence, and reraise_on_credit_or_bug in the audit except.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from audit.models import AUDIT_INPUT_SOURCES
from audit.store import AuditSampleLedger
from escape.ledger import EscapeLedger
from sampled_audit_loop import SampledAuditLoop, parse_audit_response
from subprocess_util import CreditExhaustedError
from tests.helpers import make_bg_loop_deps

_DISAGREE = '{"verdict": "disagree", "findings": "missing bounds check"}'
_AGREE = '{"verdict": "agree", "findings": ""}'


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


def _seed_merged_pr(
    repo: Path, *, pr: int = 42, path: str = "src/x.py"
) -> tuple[str, str]:
    """A base commit + one squash-merge commit ``(#pr)``. Returns (base, head)."""
    base = _head(repo)
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text("def f():\n    return 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"feat: add feature (#{pr})")
    return base, _head(repo)


class _FakeAuditor:
    """Injected adversarial-auditor stand-in — scenario-scripted response."""

    def __init__(self, response: str) -> None:
        self._response = response
        self.calls = 0

    async def audit(self, *, prompt: str) -> str:
        self.calls += 1
        _ = prompt
        return self._response


class _RaisingAuditor:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def audit(self, *, prompt: str) -> str:
        raise self._exc


def _make_state(initial_sha: str = "", *, rate: float = 1.0) -> MagicMock:
    state = MagicMock()
    store: dict[str, Any] = {"sha": initial_sha, "rate": rate, "history": []}
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
    dedup._store = store
    return dedup


def _make_prs(
    *, issue: int = 500, state: str = "OPEN", labels: list[str] | None = None
) -> MagicMock:
    prs = MagicMock()
    prs.create_issue = AsyncMock(return_value=issue)
    prs.get_issue_state = AsyncMock(return_value=state)
    prs.get_issue_labels = AsyncMock(return_value=labels or [])
    return prs


def _make_loop(
    tmp_path: Path,
    repo: Path,
    *,
    auditor: Any,
    state: MagicMock | None = None,
    dedup: MagicMock | None = None,
    prs: MagicMock | None = None,
    **config_overrides: Any,
) -> SampledAuditLoop:
    bg = make_bg_loop_deps(tmp_path)
    object.__setattr__(bg.config, "repo_root", repo)
    object.__setattr__(bg.config, "data_root", tmp_path / "data")
    object.__setattr__(bg.config, "sampled_audit_loop_enabled", True)
    object.__setattr__(bg.config, "sampled_audit_reaudit_enabled", True)
    for key, value in config_overrides.items():
        object.__setattr__(bg.config, key, value)
    return SampledAuditLoop(
        config=bg.config,
        pr_manager=prs if prs is not None else _make_prs(),
        state=state if state is not None else _make_state(),
        dedup=dedup if dedup is not None else _make_dedup(),
        deps=bg.loop_deps,
        auditor=auditor,
    )


# --- parse_audit_response --------------------------------------------------


class TestParseResponse:
    def test_disagree(self) -> None:
        assert parse_audit_response(_DISAGREE) == ("disagree", "missing bounds check")

    def test_agree(self) -> None:
        assert parse_audit_response(_AGREE)[0] == "agree"

    def test_embedded_json(self) -> None:
        assert parse_audit_response("here: " + _DISAGREE + " done")[0] == "disagree"

    def test_malformed_fails_soft_to_agree(self) -> None:
        # A malformed response must NEVER inflate the disagreement bound.
        assert parse_audit_response("garbage no json")[0] == "agree"


# --- kill-switches ---------------------------------------------------------


class TestKillSwitch:
    async def test_ui_kill_switch(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        loop = _make_loop(tmp_path, repo, auditor=_FakeAuditor(_AGREE))
        loop._enabled_cb = lambda _name: False  # type: ignore[assignment]
        assert (await loop._do_work())["status"] == "disabled"

    async def test_config_kill_switch(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        loop = _make_loop(
            tmp_path,
            repo,
            auditor=_FakeAuditor(_AGREE),
            sampled_audit_loop_enabled=False,
        )
        assert (await loop._do_work())["status"] == "config_disabled"


# --- cursor priming --------------------------------------------------------


class TestCursor:
    async def test_first_tick_primes_baseline_no_audit(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        _seed_merged_pr(repo)
        state = _make_state(initial_sha="")  # fresh install
        auditor = _FakeAuditor(_DISAGREE)
        loop = _make_loop(tmp_path, repo, auditor=auditor, state=state)
        result = await loop._do_work()
        assert result["status"] == "baseline_established"
        assert auditor.calls == 0  # no back-sample of history
        assert state._store["sha"] == _head(repo)


# --- sample + audit + record ----------------------------------------------


class TestSampleAudit:
    async def test_disagreement_recorded_and_find_filed(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        base, head = _seed_merged_pr(repo, pr=42)
        state = _make_state(initial_sha=base, rate=1.0)
        prs = _make_prs(issue=500)
        loop = _make_loop(
            tmp_path, repo, auditor=_FakeAuditor(_DISAGREE), state=state, prs=prs
        )

        result = await loop._do_work()

        assert result["status"] == "ok"
        assert result["sampled"] == 1
        assert result["disagreements"] == 1
        assert result["filed"] == 1
        prs.create_issue.assert_awaited_once()
        _title, _body = prs.create_issue.await_args.args
        assert "hydraflow-find" in prs.create_issue.await_args.kwargs["labels"]

        samples = AuditSampleLedger(loop._samples_path).read_all()
        assert len(samples) == 1
        assert samples[0].verdict == "disagree"
        assert samples[0].pr_number == 42
        assert samples[0].find_issue == 500
        # No-verdict-contamination is verifiable straight from the record.
        assert samples[0].input_sources == AUDIT_INPUT_SOURCES
        assert samples[0].no_verdict_contamination()
        assert state._store["sha"] == head

    async def test_agree_records_but_files_nothing(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        base, _head_sha = _seed_merged_pr(repo)
        state = _make_state(initial_sha=base, rate=1.0)
        prs = _make_prs()
        loop = _make_loop(
            tmp_path, repo, auditor=_FakeAuditor(_AGREE), state=state, prs=prs
        )

        result = await loop._do_work()
        assert result["sampled"] == 1
        assert result["disagreements"] == 0
        assert result["filed"] == 0
        prs.create_issue.assert_not_awaited()


# --- config_disable air-gap seam ------------------------------------------


class TestReauditSeam:
    async def test_reaudit_disabled_ticks_without_spawn(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        base, head = _seed_merged_pr(repo)
        state = _make_state(initial_sha=base, rate=1.0)
        auditor = _FakeAuditor(_DISAGREE)
        loop = _make_loop(
            tmp_path,
            repo,
            auditor=auditor,
            state=state,
            sampled_audit_reaudit_enabled=False,
        )
        result = await loop._do_work()
        assert result["status"] == "ok"
        assert result["sampled"] == 0
        assert auditor.calls == 0  # the spawn seam held: no audit ran
        assert AuditSampleLedger(loop._samples_path).read_all() == []
        assert state._store["sha"] == head  # still advances the cursor + ticks


# --- token budget cap ------------------------------------------------------


class TestBudgetCap:
    async def test_zero_budget_audits_nothing(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        base, _head_sha = _seed_merged_pr(repo)
        state = _make_state(initial_sha=base, rate=1.0)
        auditor = _FakeAuditor(_DISAGREE)
        loop = _make_loop(
            tmp_path,
            repo,
            auditor=auditor,
            state=state,
            sampled_audit_token_budget_per_tick=0,
        )
        result = await loop._do_work()
        assert result["sampled"] == 0
        assert auditor.calls == 0


# --- finding-filing budget -------------------------------------------------


class TestFindingBudget:
    async def test_per_tick_filing_cap(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        base = _head(repo)
        for i in range(4):
            (repo / f"f{i}.py").write_text(f"x = {i}\n")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", f"feat: change {i} (#{100 + i})")
        head = _head(repo)
        state = _make_state(initial_sha=base, rate=1.0)
        prs = _make_prs()
        loop = _make_loop(
            tmp_path,
            repo,
            auditor=_FakeAuditor(_DISAGREE),
            state=state,
            prs=prs,
            sampled_audit_max_issues_per_tick=2,
        )
        result = await loop._do_work()
        # All 4 disagreements recorded, but filing capped at 2 this tick.
        assert result["sampled"] == 4
        assert result["filed"] == 2
        assert prs.create_issue.await_count == 2
        assert state._store["sha"] == head


# --- adjudication reconcile ------------------------------------------------


class TestReconcile:
    async def test_upheld_crosslinks_into_escape_ledger(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        base, _head_sha = _seed_merged_pr(repo, pr=77)
        state = _make_state(initial_sha=base, rate=1.0)
        prs = _make_prs(issue=900, state="OPEN")
        loop = _make_loop(
            tmp_path, repo, auditor=_FakeAuditor(_DISAGREE), state=state, prs=prs
        )

        # Tick 1: audit + file the find issue (still open → pending).
        await loop._do_work()
        assert EscapeLedger(loop._escape_ledger_path).read_all() == []

        # Adjudication closes the find issue as upheld; tick 2 (no new commits)
        # reconciles it into the escape ledger.
        prs.get_issue_state = AsyncMock(return_value="COMPLETED")
        prs.get_issue_labels = AsyncMock(return_value=[])
        result2 = await loop._do_work()
        assert result2["status"] == "no_new_commits"

        escapes = EscapeLedger(loop._escape_ledger_path).read_all()
        assert len(escapes) == 1
        assert escapes[0].detection_source == "sampled-audit"
        assert escapes[0].originating_pr == 77
        samples = {s.id: s for s in AuditSampleLedger(loop._samples_path).read_all()}
        assert next(iter(samples.values())).disposition == "upheld"

    async def test_refuted_increments_false_alarm_no_crosslink(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        base, _head_sha = _seed_merged_pr(repo, pr=88)
        state = _make_state(initial_sha=base, rate=1.0)
        prs = _make_prs(issue=901, state="OPEN")
        loop = _make_loop(
            tmp_path, repo, auditor=_FakeAuditor(_DISAGREE), state=state, prs=prs
        )

        await loop._do_work()
        prs.get_issue_state = AsyncMock(return_value="CLOSED")
        prs.get_issue_labels = AsyncMock(return_value=["audit-refuted"])
        await loop._do_work()

        assert EscapeLedger(loop._escape_ledger_path).read_all() == []
        samples = AuditSampleLedger(loop._samples_path).read_all()
        assert samples[0].disposition == "refuted"
        from audit.metrics import false_alarm_rate

        assert false_alarm_rate(samples) == 1.0


# --- governance persistence ------------------------------------------------


class TestGovernance:
    async def test_governed_rate_persisted_each_tick(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        base, _head_sha = _seed_merged_pr(repo)
        state = _make_state(initial_sha=base, rate=0.05)
        loop = _make_loop(tmp_path, repo, auditor=_FakeAuditor(_AGREE), state=state)
        await loop._do_work()
        # A quiet (agree) tick records an observation and narrows the rate.
        assert len(state._store["history"]) == 1
        assert state._store["rate"] <= 0.05


# --- reraise_on_credit_or_bug ---------------------------------------------


class TestCreditReraise:
    async def test_credit_exhaustion_propagates(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        base, _head_sha = _seed_merged_pr(repo)
        state = _make_state(initial_sha=base, rate=1.0)
        loop = _make_loop(
            tmp_path,
            repo,
            auditor=_RaisingAuditor(CreditExhaustedError("out")),
            state=state,
        )
        with pytest.raises(CreditExhaustedError):
            await loop._do_work()
