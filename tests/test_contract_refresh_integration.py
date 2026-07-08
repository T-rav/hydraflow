"""End-to-end integration tests for :mod:`contract_refresh_loop` (§4.2 Task 21).

This file is intentionally separate from
``tests/test_contract_refresh_loop.py`` — that module mocks
:func:`contract_diff.detect_fleet_drift` and
:func:`auto_pr.generate_and_open_pr_async` as independent pinholes,
never exercising the recorder→diff→stage→PR ladder as one unit. The
integration tests below stitch those stages together against the
*real* ``detect_fleet_drift`` implementation + the real
:class:`DedupStore` file round-trip + the real PR-body synthesis,
mocking only the two genuine external surfaces:

* the per-adapter recorders (``record_github`` / ``record_git`` /
  ``record_docker`` / ``record_claude_stream``) — these spawn real
  binaries and must not run in a unit-test harness.
* :func:`auto_pr.generate_and_open_pr_async` — this shells out to
  ``git`` + ``gh`` and creates an ephemeral worktree; stubbing it keeps
  the test hermetic without coupling to the real worktree / gh auth
  machinery. Under generate-in-worktree (#9539) the loop's ``generate``
  callback writes cassettes into the worktree the helper hands it, so
  with the helper mocked the callback never runs — these tests assert
  the call kwargs (branch, labels, path_specs, callable generate) and
  that ``repo_root`` stays clean.

The replay gate (``make trust-contracts``) is mocked at the
``asyncio.create_subprocess_exec`` seam the loop reads — the same seam
the Task 16 unit tests drive — so both gate-pass and gate-fail paths
flow through the real issue-filing code.

Scope (per Task 21 of the plan):

* **Happy-path drift** — seeded mismatched cassettes flow through the
  real ``detect_fleet_drift`` → ``_open_refresh_pr`` (generate-in-worktree)
  → ``_run_replay_gate`` ladder. Assertions: PR opened with the expected
  title/labels/path_specs + callable generate, ``repo_root`` untouched,
  dedup entry persisted to JSON, replay gate invoked, no companion issue
  filed.
* **Replay-gate fail → companion issue** — same drift, but the
  replay gate exits non-zero. Assertions: refresh PR still opens,
  ``PRManager.create_issue`` fires with ``hydraflow-find`` +
  ``fake-drift`` labels and the stderr tail embedded in the body.

Each scenario completes in well under a second because there is no
real I/O to ``gh`` / ``git`` / ``docker`` / ``claude``, and the
dedup JSON round-trip is a few bytes on tmpfs.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
import yaml

import auto_pr
import contract_refresh_loop as crl_module
from auto_pr import AutoPrResult
from base_background_loop import LoopDeps
from config import HydraFlowConfig
from contract_refresh_loop import ContractRefreshLoop
from events import EventBus

# ---------------------------------------------------------------------------
# Helpers — kept local so the unit-test monkeypatch helpers from
# ``tests/test_contract_refresh_loop`` never leak into this module.
# ---------------------------------------------------------------------------


def _deps(stop: asyncio.Event, *, enabled: bool = True) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: enabled,
    )


class _FakeState:
    """Minimal in-memory stand-in for the contract-refresh StateTracker surface.

    ``ContractRefreshLoop.__init__`` stores the state ref; no integration
    scenario here exercises the Task 18 attempt counters, so a no-op
    stand-in is enough to satisfy the constructor contract without
    pulling in the filesystem-backed ``StateTracker``.
    """

    def __init__(self) -> None:
        self._attempts: dict[str, int] = {}
        self._rollups: dict[str, dict] = {}

    def get_contract_refresh_attempts(self, adapter: str) -> int:
        return int(self._attempts.get(adapter, 0))

    def inc_contract_refresh_attempts(self, adapter: str) -> int:
        self._attempts[adapter] = self._attempts.get(adapter, 0) + 1
        return self._attempts[adapter]

    def clear_contract_refresh_attempts(self, adapter: str) -> None:
        self._attempts.pop(adapter, None)

    # RollupIssueManager surface (#9359) — mirrors RollupIssueStateMixin.
    def get_rollup_issue(self, key: str) -> dict | None:
        entry = self._rollups.get(key)
        if not entry:
            return None
        return {
            "issue_number": int(entry["issue_number"]),
            "content_hash": str(entry["content_hash"]),
        }

    def set_rollup_issue(
        self, key: str, *, issue_number: int, content_hash: str
    ) -> None:
        self._rollups[key] = {
            "issue_number": int(issue_number),
            "content_hash": content_hash,
        }

    def clear_rollup_issue(self, key: str) -> None:
        self._rollups.pop(key, None)

    def get_rollup_issue_keys(self, namespace: str) -> list[str]:
        prefix = f"{namespace}:"
        return [k for k in self._rollups if k.startswith(prefix)]


def _loop(tmp_path: Path, *, prs: Any | None = None) -> ContractRefreshLoop:
    """Build a :class:`ContractRefreshLoop` rooted at ``tmp_path``.

    The loop's ``config.repo_root`` is set to ``tmp_path / "repo"``. Under
    generate-in-worktree (#9539) the loop never writes cassettes under
    ``repo_root`` at all — :meth:`_stage_drifted_cassettes` copies into the
    ephemeral worktree the PR helper hands its ``generate`` callback — so
    these tests additionally assert ``repo_root`` stays clean.
    """
    cfg = HydraFlowConfig(
        data_root=tmp_path / "data",
        repo_root=tmp_path / "repo",
        repo="hydra/hydraflow",
    )
    (tmp_path / "repo").mkdir(parents=True, exist_ok=True)
    pr_manager = prs if prs is not None else AsyncMock()
    return ContractRefreshLoop(
        config=cfg,
        prs=pr_manager,
        state=_FakeState(),
        deps=_deps(asyncio.Event(), enabled=True),
    )


def _write_committed_git_cassette(repo_root: Path, *, stdout: str) -> Path:
    """Seed a committed git cassette under the loop's repo_root.

    Returns the committed path. The ``stdout`` field is the only knob
    exercised in these tests — swap it between two calls to simulate
    drift (a fake whose observable output has changed) or leave it
    equal to simulate a clean tick.
    """
    committed_dir = repo_root / "tests" / "trust" / "contracts" / "cassettes" / "git"
    committed_dir.mkdir(parents=True, exist_ok=True)
    path = committed_dir / "commit.yaml"
    payload = {
        "adapter": "git",
        "interaction": "commit",
        "recorded_at": "2026-04-22T14:00:00Z",
        "recorder_sha": "deadbeef",
        "fixture_repo": "tests/trust/contracts/fixtures/git_sandbox",
        "input": {
            "command": "commit",
            "args": ["initial"],
            "stdin": None,
            "env": {},
        },
        "output": {
            "exit_code": 0,
            "stdout": stdout,
            "stderr": "",
        },
        "normalizers": ["sha:short"],
    }
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(payload, fh, sort_keys=False, default_flow_style=False)
    return path


def _write_recorded_git_cassette(tmp_dir: Path, *, stdout: str) -> Path:
    """Write a tmp-dir "fresh recording" cassette with the same slug.

    The recorder returns ``[<this path>]`` from the mocked seam; the
    loop then passes it into the real :func:`detect_fleet_drift` which
    diffs against the committed cassette seeded by
    :func:`_write_committed_git_cassette`.
    """
    tmp_dir.mkdir(parents=True, exist_ok=True)
    path = tmp_dir / "commit.yaml"
    payload = {
        "adapter": "git",
        "interaction": "commit",
        # Different volatile fields — stripped by canonicalization, so
        # any drift we see here is real semantic drift, not audit noise.
        "recorded_at": "2026-04-23T09:15:30Z",
        "recorder_sha": "cafef00d",
        "fixture_repo": "tests/trust/contracts/fixtures/git_sandbox",
        "input": {
            "command": "commit",
            "args": ["initial"],
            "stdin": None,
            "env": {},
        },
        "output": {
            "exit_code": 0,
            "stdout": stdout,
            "stderr": "",
        },
        "normalizers": ["sha:short"],
    }
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(payload, fh, sort_keys=False, default_flow_style=False)
    return path


class _FakeAutoPR:
    """Captures ``generate_and_open_pr_async`` calls and returns a canned result.

    The generate-in-worktree helper (#9539) is patched on ``auto_pr`` — the
    loop imports it lazily — and its ``generate`` callback is not invoked
    while the helper is mocked, so the captured kwargs carry ``generate`` +
    ``path_specs`` (no ``files``).
    """

    def __init__(self, status: str = "opened") -> None:
        self.calls: list[dict[str, Any]] = []
        self.status = status

    async def __call__(self, **kwargs: Any) -> AutoPrResult:
        self.calls.append(kwargs)
        return AutoPrResult(
            status=self.status,  # type: ignore[arg-type]
            pr_url="https://github.com/hydra/hydraflow/pull/777"
            if self.status == "opened"
            else None,
            branch=kwargs.get("branch", ""),
        )


def _stub_recorders_only_git(
    monkeypatch: pytest.MonkeyPatch, recorded_path: Path
) -> None:
    """Stub out every recorder except ``record_git``.

    The three remaining recorders return empty lists — the diff layer
    treats that as "tool missing / sandbox offline" no-signal, so only
    the git adapter's real diff fires.
    """
    monkeypatch.setattr(crl_module, "record_github", lambda *_a, **_k: [])
    monkeypatch.setattr(crl_module, "record_git", lambda *_a, **_k: [recorded_path])
    monkeypatch.setattr(crl_module, "record_docker", lambda *_a, **_k: [])
    monkeypatch.setattr(crl_module, "record_claude_stream", lambda *_a, **_k: [])


def _patch_subprocess_run(
    monkeypatch: pytest.MonkeyPatch, *, returncode: int, stderr: str = ""
) -> list[list[str]]:
    """Patch the replay-gate subprocess used by ``_run_replay_gate``.

    G14: ``_run_replay_gate`` is now async (``asyncio.create_subprocess_exec``).
    The stub returns a fake process whose ``communicate()`` resolves
    to canned bytes and whose ``returncode`` reads as configured.

    Returns a mutable list the tests can inspect after ``_do_work``
    completes. Every replay-gate call goes through this stub.
    """
    calls: list[list[str]] = []
    stdout_bytes = b"OK\n" if returncode == 0 else b"FAILED\n"
    stderr_bytes = stderr.encode()

    class _FakeProc:
        def __init__(self) -> None:
            self.returncode = returncode

        async def communicate(self) -> tuple[bytes, bytes]:
            return stdout_bytes, stderr_bytes

        async def wait(self) -> int:
            return returncode

        def kill(self) -> None:
            pass

    async def _fake_create_subprocess_exec(*argv: str, **_kwargs: Any) -> _FakeProc:
        calls.append(list(argv))
        return _FakeProc()

    monkeypatch.setattr(
        crl_module.asyncio,
        "create_subprocess_exec",
        _fake_create_subprocess_exec,
    )
    return calls


# ---------------------------------------------------------------------------
# Scenario 1 — happy-path drift end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_end_to_end_drift_opens_pr_and_records_dedup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mismatched cassette → real diff fires, PR opens, dedup persists.

    The committed cassette ships stdout ``"[main abc1234] initial\\n"``;
    the recorder side emits ``"[main feedf00d] renamed\\n"`` — the
    ``sha:short`` normalizer collapses the SHA tokens, but the commit
    *message* (``initial`` vs ``renamed``) is a real contract change
    the normalizer cannot hide, so the diff layer produces exactly one
    drifted cassette.
    """
    loop = _loop(tmp_path)
    repo_root = loop._config.repo_root

    _write_committed_git_cassette(repo_root, stdout="[main abc1234] initial\n")
    recorded = _write_recorded_git_cassette(
        tmp_path / "rec" / "git", stdout="[main feedf00d] renamed\n"
    )
    _stub_recorders_only_git(monkeypatch, recorded)

    fake_pr = _FakeAutoPR()
    monkeypatch.setattr(auto_pr, "generate_and_open_pr_async", fake_pr)

    replay_calls = _patch_subprocess_run(monkeypatch, returncode=0)

    prs = AsyncMock()
    prs.create_issue = AsyncMock(return_value=0)

    # Re-build the loop with our AsyncMock prs so the companion-issue
    # assertion below has a real spy to inspect.
    loop = _loop(tmp_path, prs=prs)
    result = await loop._do_work()

    # Real detect_fleet_drift saw the mismatched stdout and produced
    # exactly one drifted-cassette report; the tick's stats reflect it.
    assert result["status"] == "refreshed", result
    assert result["adapters_drifted"] == 1, result
    assert result["adapters_refreshed"] == 1, result
    assert result["replay_gate_passed"] is True, result
    assert result["fake_drift_issue"] is None, result
    assert result["pr_url"] == "https://github.com/hydra/hydraflow/pull/777", result

    # Auto-PR seam was called exactly once with the expected shape.
    assert len(fake_pr.calls) == 1
    kwargs = fake_pr.calls[0]
    assert kwargs["branch"].startswith("contract-refresh/")
    assert kwargs["pr_title"].startswith("contract-refresh: ")
    assert "git" in kwargs["pr_title"]
    assert "contract-refresh" in kwargs["labels"]
    assert "auto-merge" in kwargs["labels"]
    # Generate-in-worktree (#9539): no `files` kwarg — the helper gets a
    # callable `generate` and the drifted adapter's cassette dir in
    # `path_specs`. The bytes are written INTO the worktree by the callback,
    # never into repo_root.
    assert "files" not in kwargs
    assert callable(kwargs["generate"])
    assert kwargs["path_specs"] == ["tests/trust/contracts/cassettes/git"]

    # repo_root must stay clean: the committed cassette retains its ORIGINAL
    # bytes — the loop never overwrote it (that's the whole point of #9539).
    committed = repo_root / "tests/trust/contracts/cassettes/git/commit.yaml"
    committed_bytes = committed.read_bytes()
    assert b"initial" in committed_bytes, committed_bytes
    assert b"deadbeef" in committed_bytes, committed_bytes
    assert b"renamed" not in committed_bytes, committed_bytes

    # Driving the captured `generate` callback against a throwaway worktree
    # proves the PR ships the FRESH recording: it copies the recorder bytes
    # (``renamed`` / ``cafef00d``) into the worktree's committed cassette
    # path — the load-bearing invariant a no-op refresh would violate.
    fake_worktree = tmp_path / "fake_worktree"
    fake_worktree.mkdir()
    await kwargs["generate"](fake_worktree)
    generated = fake_worktree / "tests/trust/contracts/cassettes/git/commit.yaml"
    assert generated.exists(), "generate callback must write into the worktree"
    generated_bytes = generated.read_bytes()
    assert b"renamed" in generated_bytes, generated_bytes
    assert b"cafef00d" in generated_bytes, generated_bytes
    assert b"deadbeef" not in generated_bytes, generated_bytes

    # Replay gate ran exactly once.
    assert replay_calls == [["make", "trust-contracts"]]

    # Companion-issue path was NOT taken on a green replay.
    prs.create_issue.assert_not_awaited()

    # Dedup entry persisted to the per-loop JSON — a second identical
    # tick will short-circuit.
    dedup_path = loop._config.data_root / "dedup" / "contract_refresh.json"
    assert dedup_path.exists()
    text = dedup_path.read_text()
    assert text.strip() not in ("", "[]")


# ---------------------------------------------------------------------------
# Scenario 2 — replay gate fails after refresh → companion issue filed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_end_to_end_replay_gate_fail_files_fake_drift_issue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drift + red replay gate → refresh PR opens + fake-drift companion issue.

    The replay gate's ``stderr`` tail is embedded in the companion
    issue body so an operator has the diff without re-running locally.
    """
    loop = _loop(tmp_path)
    repo_root = loop._config.repo_root

    _write_committed_git_cassette(repo_root, stdout="[main abc1234] initial\n")
    recorded = _write_recorded_git_cassette(
        tmp_path / "rec" / "git", stdout="[main feedf00d] renamed\n"
    )
    _stub_recorders_only_git(monkeypatch, recorded)

    fake_pr = _FakeAutoPR()
    monkeypatch.setattr(auto_pr, "generate_and_open_pr_async", fake_pr)

    _patch_subprocess_run(
        monkeypatch,
        returncode=2,
        stderr="AssertionError: replay mismatch at fake_git commit\n",
    )

    prs = AsyncMock()
    prs.create_issue = AsyncMock(return_value=4321)
    loop = _loop(tmp_path, prs=prs)
    result = await loop._do_work()

    # Refresh PR still opens — the replay gate only decides whether a
    # companion issue is filed.
    assert len(fake_pr.calls) == 1, fake_pr.calls
    assert result["pr_url"] == "https://github.com/hydra/hydraflow/pull/777"
    assert result["replay_gate_passed"] is False
    assert result["fake_drift_issue"] == 4321

    # Companion issue was filed with the factory-routing labels + the
    # replay stderr tail embedded in the body.
    prs.create_issue.assert_awaited_once()
    # The rollup files via create_issue(title, body, labels) positionally.
    title, body, labels = prs.create_issue.await_args.args
    assert title == "Fake drift: replay gate failed after contract refresh"
    assert "hydraflow-find" in labels
    assert "fake-drift" in labels
    assert "adapter-git" in labels
    assert "replay mismatch" in body
    # The refresh PR URL is threaded into the issue body so the repair
    # implementer can open the PR straight from the companion issue.
    assert "https://github.com/hydra/hydraflow/pull/777" in body


# ---------------------------------------------------------------------------
# Scenario 3 — post-refresh quiescence: second identical tick dedups
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_second_tick_after_refresh_dedups(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After a successful refresh, an identical next tick short-circuits on dedup.

    Under generate-in-worktree (#9539) the loop NO LONGER overwrites the
    committed cassette under ``repo_root`` — the refresh bytes are written
    only into the ephemeral worktree the PR helper tears down. So the real
    ``detect_fleet_drift`` on the next tick still sees the same drift; the
    quiescence guarantee is now provided by the per-loop ``DedupStore``: the
    drift hash recorded on tick #1 short-circuits tick #2 to
    ``status="dedup_hit"`` — no second PR, no second replay gate. This is the
    load-bearing "weekly loop does not re-file an identical refresh PR every
    tick" guarantee, and it proves ``repo_root`` is never mutated.
    """
    loop = _loop(tmp_path)
    repo_root = loop._config.repo_root

    _write_committed_git_cassette(repo_root, stdout="[main abc1234] initial\n")
    recorded = _write_recorded_git_cassette(
        tmp_path / "rec" / "git", stdout="[main feedf00d] renamed\n"
    )
    _stub_recorders_only_git(monkeypatch, recorded)

    fake_pr = _FakeAutoPR()
    monkeypatch.setattr(auto_pr, "generate_and_open_pr_async", fake_pr)
    replay_calls = _patch_subprocess_run(monkeypatch, returncode=0)

    prs = AsyncMock()
    prs.create_issue = AsyncMock(return_value=0)
    loop = _loop(tmp_path, prs=prs)
    repo_root = loop._config.repo_root
    _write_committed_git_cassette(repo_root, stdout="[main abc1234] initial\n")

    # Tick #1: drift → PR filed → dedup key recorded.
    first = await loop._do_work()
    assert first["status"] == "refreshed"
    assert len(fake_pr.calls) == 1
    assert len(replay_calls) == 1

    # repo_root was NOT mutated — the committed cassette still holds the
    # original bytes (the refresh diff lives only in the torn-down worktree).
    committed = repo_root / "tests/trust/contracts/cassettes/git/commit.yaml"
    assert b"initial" in committed.read_bytes()
    assert b"renamed" not in committed.read_bytes()

    # Tick #2: same drift, but the dedup hash short-circuits before any PR.
    second = await loop._do_work()
    assert second["status"] == "dedup_hit", second
    assert second["adapters_drifted"] == 1
    assert len(fake_pr.calls) == 1, "dedup tick must not fire a second PR"
    assert len(replay_calls) == 1, "dedup tick must not fire a second replay gate"
