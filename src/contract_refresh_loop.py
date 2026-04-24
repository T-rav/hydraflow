"""ContractRefreshLoop — weekly cassette refresh for fake contract tests (§4.2).

Tick body (Tasks 15 + 16 wired; Tasks 17+ still pending):

1. Record cassettes against live ``gh``/``git``/``docker``/``claude`` into a
   tmp directory (``contract_recording.record_*``).
2. Diff the fresh recordings against the committed cassettes
   (``contract_diff.detect_fleet_drift``). No drift → status dict with
   ``adapters_drifted=0``.
3. If drift is detected, hash the drift report and look the hash up in a
   per-loop :class:`DedupStore`. Hash hit → short-circuit so identical
   drift on back-to-back ticks does not refile the same PR.
4. Stage the drifted/new cassettes into the worktree (their committed
   paths under ``tests/trust/contracts/``) and open a refresh PR via
   :func:`auto_pr.open_automated_pr_async` — title ``contract-refresh:
   YYYY-MM-DD (<adapters>)``, body summarising per-adapter slugs, labels
   ``contract-refresh`` + ``auto-merge``, ``auto_merge=True``,
   ``raise_on_failure=False``.
5. Post-refresh replay gate (Task 16): invoke ``make trust-contracts``
   via :func:`subprocess.run`. Pass → clean exit. Fail → the fresh
   cassettes have outrun the fakes; file a ``hydraflow-find`` +
   ``fake-drift`` companion issue via ``PRManager.create_issue`` so the
   factory dispatches a fake-repair implementer. Success of the PR's
   auto-merge is not gated on replay; the replay gate only decides
   whether to file the companion issue. Dedup is recorded regardless so
   we never double-file.

Kill-switch: :meth:`LoopDeps.enabled_cb` with
``worker_name="contract_refresh"``.

Tasks 17+ (stream-protocol drift routing, escalation tracker, wiring,
telemetry, scenario) land in subsequent PRs.

Spec: ``docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md``
§4.2 "ContractRefreshLoop — full caretaker (refresh + auto-repair)".
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from auto_pr import open_automated_pr_async
from base_background_loop import BaseBackgroundLoop, LoopDeps  # noqa: TCH001
from contract_diff import (
    AdapterDriftReport,
    FleetDriftReport,
    detect_fleet_drift,
)
from contract_recording import (
    record_claude_stream,
    record_docker,
    record_git,
    record_github,
)
from dedup_store import DedupStore
from models import WorkCycleResult  # noqa: TCH001

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.contract_refresh_loop")

# The committed sandbox repo the GitHub recorder targets. Centralised here
# so tests (and the eventual config field in Task 18+) can override in one
# place. Matches ``docs/superpowers/plans/2026-04-22-fake-contract-tests.md``
# Task 0.
_SANDBOX_GITHUB_REPO = "T-rav-Hydra-Ops/hydraflow-contracts-sandbox"

# Hard cap on the replay-gate subprocess — defends the async event loop
# when a recorder hangs on network I/O or a zombie subprocess.
_REPLAY_GATE_TIMEOUT_SECONDS = 300
# Fixture git sandbox seeded by Task 0 (relative to ``repo_root``).
_GIT_SANDBOX_RELPATH = "tests/trust/contracts/fixtures/git_sandbox"


@dataclass(frozen=True)
class AdapterPlan:
    """Per-adapter recording configuration.

    The ``name`` field identifies the adapter (``github``/``git``/``docker``/
    ``claude``); ``cassette_dir_relpath`` points at the committed cassette
    directory relative to the repo root. Tasks 13–18 consume these entries
    to drive per-adapter recording, diffing, and drift escalation.
    """

    name: str  # "github" | "git" | "docker" | "claude"
    cassette_dir_relpath: str  # under repo_root


ADAPTER_PLANS: tuple[AdapterPlan, ...] = (
    AdapterPlan(
        name="github", cassette_dir_relpath="tests/trust/contracts/cassettes/github"
    ),
    AdapterPlan(name="git", cassette_dir_relpath="tests/trust/contracts/cassettes/git"),
    AdapterPlan(
        name="docker", cassette_dir_relpath="tests/trust/contracts/cassettes/docker"
    ),
    AdapterPlan(
        name="claude", cassette_dir_relpath="tests/trust/contracts/claude_streams"
    ),
)


class ContractRefreshLoop(BaseBackgroundLoop):
    """Weekly refresh of fake-contract cassettes with autonomous repair dispatch.

    Tick body (Tasks 15 + 16) records, diffs, stages, PR-files, and
    replay-gates. Tasks 17+ add:

    * Stream-protocol drift routing (`stream-protocol-drift` issues).
    * Per-adapter 3-attempt repair tracker; exhaustion →
      ``hitl-escalation`` + ``fake-repair-stuck`` / ``stream-parser-stuck``.
    """

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        deps: LoopDeps,
        prs: PRManager,
        state: StateTracker,
    ) -> None:
        super().__init__(
            worker_name="contract_refresh",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._prs = prs
        self._state = state
        self._dedup = DedupStore(
            "contract_refresh",
            config.data_root / "dedup" / "contract_refresh.json",
        )

    def _get_default_interval(self) -> int:
        return self._config.contract_refresh_interval

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def _record_all(self, tmp_root: Path) -> dict[str, list[Path]]:
        """Run each adapter's recorder into a dedicated tmp subdirectory.

        Returns a ``{adapter_name: [recorded_paths]}`` mapping suitable
        for :func:`contract_diff.detect_fleet_drift`. An empty list for
        an adapter is the recorder's way of signalling "tool missing /
        sandbox offline" — the diff layer already treats that as
        no-signal (vs a catastrophic all-deleted sweep).
        """
        gh_dir = tmp_root / "github"
        git_dir = tmp_root / "git"
        docker_dir = tmp_root / "docker"
        claude_dir = tmp_root / "claude"

        sandbox_dir = self._config.repo_root / _GIT_SANDBOX_RELPATH

        return {
            "github": record_github(_SANDBOX_GITHUB_REPO, gh_dir),
            "git": record_git(sandbox_dir, git_dir),
            "docker": record_docker(docker_dir),
            "claude": record_claude_stream(claude_dir),
        }

    # ------------------------------------------------------------------
    # Drift → PR
    # ------------------------------------------------------------------

    def _dedup_key(self, fleet: FleetDriftReport) -> str:
        """Stable content hash keyed on the drifted/new/deleted slug sets.

        Volatile metadata inside each cassette is already stripped by
        :func:`contract_diff._canonical_payload`, so keying off filename
        sets is sufficient: two ticks that diff the same slugs the same
        way against the same committed tree will produce the same key.
        """
        payload = {
            "reports": [
                {
                    "adapter": r.adapter,
                    "drifted": sorted(p.name for p in r.drifted_cassettes),
                    "new": sorted(p.name for p in r.new_cassettes),
                    "deleted": sorted(p.name for p in r.deleted_cassettes),
                }
                for r in sorted(fleet.reports, key=lambda r: r.adapter)
            ]
        }
        blob = json.dumps(payload, sort_keys=True).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()

    def _stage_drifted_cassettes(self, reports: list[AdapterDriftReport]) -> list[Path]:
        """Copy each drifted/new cassette into its committed path under ``repo_root``.

        ``auto_pr.open_automated_pr_async`` reads the file bytes from the
        paths we return and stages them into the ephemeral worktree, so
        we *must* write to paths under ``repo_root``. Returns the list
        of committed paths that now hold the fresh bytes.
        """
        written: list[Path] = []
        plans_by_name = {p.name: p for p in ADAPTER_PLANS}
        for report in reports:
            plan = plans_by_name[report.adapter]
            committed_dir = self._config.repo_root / plan.cassette_dir_relpath
            committed_dir.mkdir(parents=True, exist_ok=True)
            for src in [*report.drifted_cassettes, *report.new_cassettes]:
                dst = committed_dir / src.name
                dst.write_bytes(src.read_bytes())
                written.append(dst)
        return written

    def _pr_title_and_body(
        self, fleet: FleetDriftReport, stamp: str
    ) -> tuple[str, str]:
        adapters_drifted = sorted({r.adapter for r in fleet.reports})
        adapters_joined = ", ".join(adapters_drifted)
        title = f"contract-refresh: {stamp} ({adapters_joined})"

        body_lines: list[str] = [
            "Automated cassette refresh by `ContractRefreshLoop`.",
            "",
            f"Adapters drifted: **{adapters_joined}**.",
            "",
            "Per-adapter slugs:",
        ]
        for report in sorted(fleet.reports, key=lambda r: r.adapter):
            drifted_names = sorted(p.name for p in report.drifted_cassettes)
            new_names = sorted(p.name for p in report.new_cassettes)
            deleted_names = sorted(p.name for p in report.deleted_cassettes)
            segments: list[str] = []
            if drifted_names:
                segments.append("drifted=" + ",".join(drifted_names))
            if new_names:
                segments.append("new=" + ",".join(new_names))
            if deleted_names:
                segments.append("deleted=" + ",".join(deleted_names))
            body_lines.append(f"- `{report.adapter}`: " + "; ".join(segments))
        body_lines.extend(
            [
                "",
                (
                    "Replay gate (`make trust-contracts`) runs after PR opens; on "
                    "failure a `fake-drift` companion issue routes repair through "
                    "the factory."
                ),
            ]
        )
        return title, "\n".join(body_lines)

    async def _open_refresh_pr(
        self, written: list[Path], fleet: FleetDriftReport
    ) -> str | None:
        stamp = datetime.now(UTC).strftime("%Y-%m-%d")
        branch = f"contract-refresh/{stamp}"
        title, body = self._pr_title_and_body(fleet, stamp)

        result = await open_automated_pr_async(
            repo_root=self._config.repo_root,
            branch=branch,
            files=written,
            pr_title=title,
            pr_body=body,
            commit_message=title,
            auto_merge=True,
            raise_on_failure=False,
            labels=["contract-refresh", "auto-merge"],
        )
        if result.status not in ("opened",):
            logger.warning(
                "contract_refresh: PR creation returned status=%s error=%s",
                result.status,
                getattr(result, "error", None),
            )
            return None
        return result.pr_url

    # ------------------------------------------------------------------
    # Replay gate (Task 16)
    # ------------------------------------------------------------------

    def _run_replay_gate(self) -> subprocess.CompletedProcess[str]:
        """Invoke ``make trust-contracts`` and capture its output.

        Synchronous on purpose: the refresh tick runs once a week and
        wrapping this in ``asyncio.create_subprocess_exec`` would add
        complexity for no real benefit. Task 20's telemetry instrumentation
        will push this through ``asyncio.to_thread`` if/when the base
        loop's timing budget becomes load-bearing.

        Hard timeout defends the orchestrator: a hung recording cassette
        (network call inside a recorder, zombie subprocess, etc.) must
        not stall the entire async event loop indefinitely. On
        ``TimeoutExpired`` we synthesize a non-zero CompletedProcess so
        the caller routes the timeout through the fake-drift companion
        path.
        """
        try:
            return subprocess.run(  # noqa: S603
                ["make", "trust-contracts"],
                cwd=str(self._config.repo_root),
                capture_output=True,
                text=True,
                check=False,
                timeout=_REPLAY_GATE_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            logger.warning(
                "Replay gate timed out after %ss; treating as failure",
                _REPLAY_GATE_TIMEOUT_SECONDS,
            )
            stdout_txt = (
                exc.stdout.decode()
                if isinstance(exc.stdout, bytes)
                else (exc.stdout or "")
            )
            stderr_txt = (
                exc.stderr.decode()
                if isinstance(exc.stderr, bytes)
                else (exc.stderr or "")
            )
            return subprocess.CompletedProcess(
                args=list(exc.cmd)
                if isinstance(exc.cmd, list | tuple)
                else [str(exc.cmd)],
                returncode=124,  # standard bash convention for timeouts
                stdout=stdout_txt,
                stderr=stderr_txt
                + f"\n[replay-gate-timeout {_REPLAY_GATE_TIMEOUT_SECONDS}s]",
            )

    async def _file_fake_drift_issue(
        self,
        adapters: list[str],
        replay_proc: subprocess.CompletedProcess[str],
        pr_url: str | None,
    ) -> int:
        adapters_joined = ", ".join(adapters)
        labels = ["hydraflow-find", "fake-drift"]
        for adapter in adapters:
            labels.append(f"adapter-{adapter}")

        title = (
            f"Fake drift: replay gate failed after contract refresh ({adapters_joined})"
        )
        pr_line = f"Refresh PR: {pr_url}" if pr_url else "Refresh PR: (not opened)"
        # Clip replay output so the issue body stays reviewable.
        stdout_tail = (replay_proc.stdout or "").strip()[-2000:]
        stderr_tail = (replay_proc.stderr or "").strip()[-2000:]
        body = (
            "`ContractRefreshLoop` refreshed cassettes for "
            f"**{adapters_joined}** and the post-refresh replay gate "
            "(`make trust-contracts`) failed — one or more fakes have "
            "diverged from the committed cassette.\n\n"
            f"{pr_line}\n\n"
            "**Repair path.** Check out the refresh branch, run "
            "`PYTHONPATH=src uv run make trust-contracts` locally, inspect the "
            "diff, adjust the matching fake in `tests/scenarios/fakes/`, and "
            "land the fake-side fix PR.\n\n"
            "### replay gate stdout (tail)\n"
            f"```\n{stdout_tail}\n```\n\n"
            "### replay gate stderr (tail)\n"
            f"```\n{stderr_tail}\n```\n"
        )
        return await self._prs.create_issue(
            title=title,
            body=body,
            labels=labels,
        )

    # ------------------------------------------------------------------
    # Tick
    # ------------------------------------------------------------------

    async def _do_work(self) -> WorkCycleResult:
        """Record → diff → (maybe) PR + replay gate.

        The kill-switch short-circuits with ``{"status": "disabled"}`` so
        the base-class status reporter still has something to publish.
        """
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}

        tmp_root = self._config.data_root / "contract_refresh" / "recordings"
        tmp_root.mkdir(parents=True, exist_ok=True)
        recordings = self._record_all(tmp_root)

        fleet: FleetDriftReport = detect_fleet_drift(recordings, self._config.repo_root)

        if not fleet.has_drift:
            return {
                "status": "clean",
                "adapters_refreshed": 0,
                "adapters_drifted": 0,
            }

        dedup_key = self._dedup_key(fleet)
        if dedup_key in self._dedup.get():
            logger.info(
                "contract_refresh: drift already dispatched (dedup hit %s)",
                dedup_key[:12],
            )
            return {
                "status": "dedup_hit",
                "adapters_refreshed": 0,
                "adapters_drifted": len(fleet.reports),
            }

        written = self._stage_drifted_cassettes(fleet.reports)
        pr_url = await self._open_refresh_pr(written, fleet)
        # Only record the dedup key after a successful PR open. A
        # transient failure (branch conflict, ``gh`` auth, push rejection)
        # must not be hidden by dedup — the next tick retries. Without
        # this guard the primary checkout stays dirty with uncommitted
        # cassette writes while dedup blocks re-filing — silent stuck.
        if pr_url is not None:
            self._dedup.add(dedup_key)

        # Task 16 — replay gate. Only filed as fake-drift when the replay
        # suite fails after the refresh PR has been opened.
        replay_proc = self._run_replay_gate()
        fake_drift_issue: int | None = None
        if replay_proc.returncode != 0:
            adapters_drifted = sorted({r.adapter for r in fleet.reports})
            fake_drift_issue = await self._file_fake_drift_issue(
                adapters_drifted, replay_proc, pr_url
            )

        return {
            "status": "refreshed",
            "adapters_refreshed": len(written),
            "adapters_drifted": len(fleet.reports),
            "pr_url": pr_url,
            "replay_gate_passed": replay_proc.returncode == 0,
            "fake_drift_issue": fake_drift_issue,
        }
