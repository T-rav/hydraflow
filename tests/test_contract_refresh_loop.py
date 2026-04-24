"""Unit tests for src/contract_refresh_loop.py (§4.2 Phase 2).

Covers the Task 11/12 skeleton surface plus the Task 15/16 PR-filing +
replay-gate wiring:

- construction (worker_name wired, deps stored)
- ``_get_default_interval`` reads ``config.contract_refresh_interval``
- ``_do_work`` short-circuits with ``{"status": "disabled"}`` when the
  ``enabled_cb`` kill-switch returns ``False``
- Task 15: on drift, stages cassettes + calls
  ``auto_pr.open_automated_pr_async`` with the right title/body/labels
  and records a dedup key so identical drift does not refile.
- Task 16: after the refresh PR opens, re-runs ``make trust-contracts``
  via subprocess. Replay failure → ``hydraflow-find`` + ``fake-drift``
  issue via ``PRManager.create_issue``. Replay pass → no companion issue.

Tasks 17+ (stream-protocol drift, escalation tracker, wiring, telemetry)
remain out of scope for this PR and are not exercised here.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import contract_refresh_loop as crl_module
from auto_pr import AutoPrResult
from base_background_loop import LoopDeps
from config import HydraFlowConfig
from contract_refresh_loop import ContractRefreshLoop
from events import EventBus


def _deps(stop: asyncio.Event, *, enabled: bool = True) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: enabled,
    )


def _loop(
    tmp_path: Path,
    *,
    enabled: bool = True,
    prs: Any | None = None,
    **config_overrides: object,
) -> ContractRefreshLoop:
    cfg = HydraFlowConfig(
        data_root=tmp_path / "data",
        repo_root=tmp_path / "repo",
        repo="hydra/hydraflow",
        **config_overrides,
    )
    (tmp_path / "repo").mkdir(parents=True, exist_ok=True)
    pr_manager = prs if prs is not None else AsyncMock()
    state = MagicMock()
    return ContractRefreshLoop(
        config=cfg,
        prs=pr_manager,
        state=state,
        deps=_deps(asyncio.Event(), enabled=enabled),
    )


# ---------------------------------------------------------------------------
# Skeleton tests (Tasks 11/12)
# ---------------------------------------------------------------------------


def test_loop_constructs_with_expected_worker_name(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    assert loop._worker_name == "contract_refresh"


def test_default_interval_reads_from_config(tmp_path: Path) -> None:
    # Default from the ``contract_refresh_interval`` Field (weekly cadence).
    loop = _loop(tmp_path)
    assert loop._get_default_interval() == 604800


def test_default_interval_reflects_config_override(tmp_path: Path) -> None:
    loop = _loop(tmp_path, contract_refresh_interval=86400)
    assert loop._get_default_interval() == 86400


def test_do_work_short_circuits_when_kill_switch_disabled(tmp_path: Path) -> None:
    loop = _loop(tmp_path, enabled=False)
    result = asyncio.run(loop._do_work())
    assert result == {"status": "disabled"}


# ---------------------------------------------------------------------------
# Task 15 / 16 helpers
# ---------------------------------------------------------------------------


def _stub_recording(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub ``contract_recording.record_*`` to return empty cassette lists.

    Individual tests that want to simulate fresh recordings override the
    relevant ``record_*`` entry after this helper runs.
    """
    monkeypatch.setattr(crl_module, "record_github", lambda *_a, **_k: [])
    monkeypatch.setattr(crl_module, "record_git", lambda *_a, **_k: [])
    monkeypatch.setattr(crl_module, "record_docker", lambda *_a, **_k: [])
    monkeypatch.setattr(crl_module, "record_claude_stream", lambda *_a, **_k: [])


def _stub_make_trust_contracts_ok(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Stub ``subprocess.run`` used for ``make trust-contracts`` to return ok.

    Returns a mutable list of invoked argv for assertions.
    """
    calls: list[list[str]] = []

    def _fake_run(
        argv: list[str], *_a: Any, **_k: Any
    ) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return subprocess.CompletedProcess(
            args=argv, returncode=0, stdout="ok", stderr=""
        )

    monkeypatch.setattr(crl_module.subprocess, "run", _fake_run)
    return calls


def _stub_make_trust_contracts_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> list[list[str]]:
    calls: list[list[str]] = []

    def _fake_run(
        argv: list[str], *_a: Any, **_k: Any
    ) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return subprocess.CompletedProcess(
            args=argv,
            returncode=2,
            stdout="FAILED tests/trust/contracts/test_fake_git_contract.py",
            stderr="replay mismatch",
        )

    monkeypatch.setattr(crl_module.subprocess, "run", _fake_run)
    return calls


class _FakeAutoPR:
    """Captures ``open_automated_pr_async`` calls and returns a canned result."""

    def __init__(self, status: str = "opened") -> None:
        self.calls: list[dict[str, Any]] = []
        self.status = status

    async def __call__(self, **kwargs: Any) -> AutoPrResult:
        self.calls.append(kwargs)
        return AutoPrResult(
            status=self.status,  # type: ignore[arg-type]
            pr_url="https://github.com/x/y/pull/42"
            if self.status == "opened"
            else None,
            branch=kwargs.get("branch", ""),
        )


def _seed_recorded_cassette(tmp_dir: Path, adapter: str, slug: str) -> Path:
    """Write a stub recorded cassette under ``tmp_dir`` so diff can see it."""
    suffix = ".jsonl" if adapter == "claude" else ".yaml"
    path = tmp_dir / f"{slug}{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"recorded-bytes-v2")
    return path


# ---------------------------------------------------------------------------
# Task 15: refresh PR opening
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_do_work_no_drift_no_pr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """All adapters clean → no PR, no replay gate run, no issue."""
    _stub_recording(monkeypatch)
    fake = _FakeAutoPR()
    monkeypatch.setattr(crl_module, "open_automated_pr_async", fake)
    calls = _stub_make_trust_contracts_ok(monkeypatch)

    # Force detect_fleet_drift to report no drift regardless of input.
    monkeypatch.setattr(
        crl_module,
        "detect_fleet_drift",
        lambda *_a, **_k: crl_module.FleetDriftReport(reports=[], has_drift=False),
    )

    loop = _loop(tmp_path)
    result = await loop._do_work()

    assert fake.calls == []
    assert calls == []  # replay gate not invoked when no drift
    assert isinstance(result, dict)
    assert result.get("adapters_drifted") == 0


@pytest.mark.asyncio
async def test_do_work_drift_opens_refresh_pr_and_records_dedup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drift detected → refresh PR opened with the right title/body/labels.

    Also verifies a dedup key lands in ``contract_refresh.json`` so a
    second identical tick will short-circuit.
    """
    _stub_recording(monkeypatch)
    # Simulate that ``record_git`` produced a cassette.
    recorded_git = _seed_recorded_cassette(tmp_path / "rec" / "git", "git", "commit")
    monkeypatch.setattr(crl_module, "record_git", lambda *_a, **_k: [recorded_git])

    drifted_report = crl_module.AdapterDriftReport(
        adapter="git",
        drifted_cassettes=[recorded_git],
        new_cassettes=[],
        deleted_cassettes=[],
    )
    fleet = crl_module.FleetDriftReport(reports=[drifted_report], has_drift=True)
    monkeypatch.setattr(crl_module, "detect_fleet_drift", lambda *_a, **_k: fleet)

    fake = _FakeAutoPR()
    monkeypatch.setattr(crl_module, "open_automated_pr_async", fake)
    _stub_make_trust_contracts_ok(monkeypatch)

    loop = _loop(tmp_path)
    result = await loop._do_work()

    assert len(fake.calls) == 1
    kwargs = fake.calls[0]
    assert kwargs["branch"].startswith("contract-refresh/")
    assert "contract-refresh" in kwargs["pr_title"]
    assert "git" in kwargs["pr_body"]
    labels = kwargs.get("labels") or []
    assert "contract-refresh" in labels
    # At least the drifted cassette is in the file list.
    staged_names = [Path(p).name for p in kwargs["files"]]
    assert "commit.yaml" in staged_names

    # Dedup key recorded.
    dedup_path = loop._config.data_root / "dedup" / "contract_refresh.json"
    assert dedup_path.exists()
    assert dedup_path.read_text().strip() not in ("", "[]")

    assert isinstance(result, dict)
    assert result.get("adapters_drifted", 0) >= 1


@pytest.mark.asyncio
async def test_do_work_dedup_hit_skips_pr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Identical drift on a second tick must not open a second PR."""
    _stub_recording(monkeypatch)
    recorded_git = _seed_recorded_cassette(tmp_path / "rec" / "git", "git", "commit")
    monkeypatch.setattr(crl_module, "record_git", lambda *_a, **_k: [recorded_git])

    drifted_report = crl_module.AdapterDriftReport(
        adapter="git",
        drifted_cassettes=[recorded_git],
        new_cassettes=[],
        deleted_cassettes=[],
    )
    fleet = crl_module.FleetDriftReport(reports=[drifted_report], has_drift=True)
    monkeypatch.setattr(crl_module, "detect_fleet_drift", lambda *_a, **_k: fleet)

    fake = _FakeAutoPR()
    monkeypatch.setattr(crl_module, "open_automated_pr_async", fake)
    _stub_make_trust_contracts_ok(monkeypatch)

    loop = _loop(tmp_path)

    # First tick: PR filed.
    await loop._do_work()
    assert len(fake.calls) == 1

    # Second tick: dedup hit, no additional PR.
    await loop._do_work()
    assert len(fake.calls) == 1


# ---------------------------------------------------------------------------
# Task 16: replay gate + fake-drift companion issue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_do_work_replay_gate_fails_files_companion_issue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replay fails after refresh PR → hydraflow-find + fake-drift issue."""
    _stub_recording(monkeypatch)
    recorded_git = _seed_recorded_cassette(tmp_path / "rec" / "git", "git", "commit")
    monkeypatch.setattr(crl_module, "record_git", lambda *_a, **_k: [recorded_git])
    drifted_report = crl_module.AdapterDriftReport(
        adapter="git",
        drifted_cassettes=[recorded_git],
        new_cassettes=[],
        deleted_cassettes=[],
    )
    fleet = crl_module.FleetDriftReport(reports=[drifted_report], has_drift=True)
    monkeypatch.setattr(crl_module, "detect_fleet_drift", lambda *_a, **_k: fleet)

    fake = _FakeAutoPR()
    monkeypatch.setattr(crl_module, "open_automated_pr_async", fake)
    calls = _stub_make_trust_contracts_fail(monkeypatch)

    prs = AsyncMock()
    prs.create_issue = AsyncMock(return_value=101)
    loop = _loop(tmp_path, prs=prs)
    await loop._do_work()

    # Replay gate was invoked (``make trust-contracts``).
    assert calls, "make trust-contracts should have been invoked"
    assert calls[0][:2] == ["make", "trust-contracts"]

    # Companion issue filed with the right labels.
    prs.create_issue.assert_awaited()
    kwargs = prs.create_issue.await_args.kwargs
    assert "hydraflow-find" in kwargs["labels"]
    assert "fake-drift" in kwargs["labels"]
    assert "trust-contracts" in kwargs["body"] or "replay" in kwargs["body"].lower()


@pytest.mark.asyncio
async def test_do_work_replay_gate_passes_no_companion_issue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replay passes after refresh PR → no companion issue filed."""
    _stub_recording(monkeypatch)
    recorded_git = _seed_recorded_cassette(tmp_path / "rec" / "git", "git", "commit")
    monkeypatch.setattr(crl_module, "record_git", lambda *_a, **_k: [recorded_git])
    drifted_report = crl_module.AdapterDriftReport(
        adapter="git",
        drifted_cassettes=[recorded_git],
        new_cassettes=[],
        deleted_cassettes=[],
    )
    fleet = crl_module.FleetDriftReport(reports=[drifted_report], has_drift=True)
    monkeypatch.setattr(crl_module, "detect_fleet_drift", lambda *_a, **_k: fleet)

    fake = _FakeAutoPR()
    monkeypatch.setattr(crl_module, "open_automated_pr_async", fake)
    _stub_make_trust_contracts_ok(monkeypatch)

    prs = AsyncMock()
    prs.create_issue = AsyncMock(return_value=0)
    loop = _loop(tmp_path, prs=prs)
    await loop._do_work()

    prs.create_issue.assert_not_awaited()
