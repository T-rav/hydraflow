"""DiagramLoop (L24) — autonomous regeneration of architecture knowledge.

Per ADR-0029 (caretaker pattern), ADR-0049 (kill-switch convention),
and the architecture knowledge system spec (§4.4).

Tick behavior:
  1. Run runner.emit() against the current working tree.
  2. git status --porcelain on docs/arch/generated/ and .meta.json.
  3. If empty: log "no drift", return.
  4. Otherwise: open (or update) a single PR using auto_pr.open_automated_pr_async.
     The branch is fixed (arch-regen-auto) so re-running force-pushes and
     either creates a new PR or updates the existing one — gh handles
     idempotence at the branch level (open PR for branch already exists).
  5. Run the functional-area coverage check; if it fails, open
     a "chore(arch): unassigned functional area" issue (separate from
     the regen PR) via PRPort.find_existing_issue + create_issue.

Kill switch: HYDRAFLOW_DISABLE_DIAGRAM_LOOP=1.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from models import WorkCycleResult

if TYPE_CHECKING:
    from auto_pr import AutoPrResult

logger = logging.getLogger(__name__)

_KILL_SWITCH_ENV = "HYDRAFLOW_DISABLE_DIAGRAM_LOOP"
_REGEN_BRANCH = "arch-regen-auto"
_PR_TITLE_PREFIX = "chore(arch): regenerate architecture knowledge"
_COVERAGE_ISSUE_TITLE = "chore(arch): unassigned functional area"


class DiagramLoop(BaseBackgroundLoop):
    """L24 caretaker — keeps docs/arch/generated/ in sync with src/.

    Per ADR-0029, ADR-0049.
    """

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        pr_manager,  # PRPort
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="diagram_loop",
            config=config,
            deps=deps,
        )
        self._pr_manager = pr_manager
        self._repo_root = Path.cwd()

    def _set_repo_root(self, path: Path) -> None:
        """Test seam: redirect the loop at a worktree without subclassing."""
        self._repo_root = Path(path)

    def _get_default_interval(self) -> int:
        # 4 hours; configurable via HydraFlowConfig
        return 14400

    async def _do_work(self) -> WorkCycleResult:
        # ADR-0049 in-body kill-switch (UI toggle, System tab). Must be FIRST.
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.diagram_loop_enabled:
            return {"status": "config_disabled"}
        # Kill-switch (ADR-0049). Belt and suspenders.
        if os.environ.get(_KILL_SWITCH_ENV) == "1":
            return {"skipped": "kill_switch"}

        result = await self._regen_pr()
        if result is None:
            return {"drift": None}
        if result.status == "no-diff":
            return {"drift": False}
        # A PR opened → the committed arch drifted from source. Also run the
        # functional-area coverage check (separate issue, not the regen PR).
        await self._ensure_coverage_issue()
        return {"drift": True, "pr_url": result.pr_url}

    async def _regen_pr(self) -> AutoPrResult | None:
        """Regenerate the arch artifacts INSIDE an ephemeral worktree (branched
        off the base) and open/update the regen PR — ``repo_root`` is never
        mutated (#9539). Branch is fixed (``arch-regen-auto``); gh handles
        open-or-update idempotence at the branch level. Returns the
        ``AutoPrResult`` (``opened``/``no-diff``), or ``None`` on failure.
        """
        from datetime import UTC, datetime  # noqa: PLC0415

        from auto_pr import generate_and_open_pr_async  # noqa: PLC0415

        today = datetime.now(UTC).strftime("%Y-%m-%d")

        async def _generate(worktree: Path) -> None:
            # Re-extract arch artifacts from the worktree's (base) source into
            # the worktree's out_dir — never the host checkout. Wrapped in a
            # thread: emit() is sync CPU/IO work.
            from arch.runner import emit  # noqa: PLC0415

            await asyncio.to_thread(
                emit, repo_root=worktree, out_dir=worktree / "docs/arch/generated"
            )

        result = await generate_and_open_pr_async(
            repo_root=self._repo_root,
            branch=_REGEN_BRANCH,
            generate=_generate,
            path_specs=["docs/arch/generated", "docs/arch/.meta.json"],
            pr_title=f"{_PR_TITLE_PREFIX} — {today}",
            pr_body=self._build_pr_body(),
            base=self._config.base_branch(),
            auto_merge=True,
            labels=["hydraflow-ready", "arch-regen"],
            raise_on_failure=False,
        )
        if result.status == "failed":
            logger.warning("DiagramLoop regen PR failed: %s", result.error)
            return None
        return result

    def _build_pr_body(self) -> str:
        return "\n".join(
            [
                "Auto-generated by `DiagramLoop` (L24). The architecture knowledge",
                "artifacts in `docs/arch/generated/` were re-extracted from source",
                "inside an ephemeral worktree off the base branch — the factory's",
                "checkout is never touched (#9539) — and the diff is in this PR.",
                "",
                "Per ADR-0029 caretaker pattern. Auto-merges once CI passes",
                "(arch-regen guard, quality, scenario tests).",
            ]
        )

    async def _unassigned_items(self) -> dict[str, list[str]]:
        """Return {'loops': [...], 'ports': [...]} of items in code but not in YAML."""
        from arch._functional_areas_schema import (  # noqa: PLC0415
            load_functional_areas,
        )
        from arch.extractors.loops import extract_loops  # noqa: PLC0415
        from arch.extractors.ports import extract_ports  # noqa: PLC0415

        src_dir = self._repo_root / "src"
        fakes_dir = self._repo_root / "src/mockworld/fakes"
        yaml_path = self._repo_root / "docs/arch/functional_areas.yml"

        if not yaml_path.exists():
            return {"loops": [], "ports": []}

        fa = load_functional_areas(yaml_path)
        assigned_loops: set[str] = set()
        assigned_ports: set[str] = set()
        for area in fa.areas.values():
            assigned_loops.update(area.loops)
            assigned_ports.update(area.ports)

        discovered_loops = {info.name for info in extract_loops(src_dir)}
        discovered_ports = {
            info.name for info in extract_ports(src_dir=src_dir, fakes_dir=fakes_dir)
        }
        return {
            "loops": sorted(discovered_loops - assigned_loops),
            "ports": sorted(discovered_ports - assigned_ports),
        }

    async def _ensure_coverage_issue(self) -> None:
        items = await self._unassigned_items()
        if not items["loops"] and not items["ports"]:
            # Resolved — every loop/port is now assigned to a functional area.
            # Close the open coverage issue if one exists (#9359 issue-hygiene)
            # rather than leaving it stale forever.
            open_number = await self._pr_manager.find_existing_issue(
                _COVERAGE_ISSUE_TITLE
            )
            if open_number:
                await self._pr_manager.post_comment(
                    open_number,
                    "All loops/ports are now assigned to a functional area — "
                    "auto-closing.",
                )
                await self._pr_manager.close_issue(open_number)
            return
        existing_number = await self._pr_manager.find_existing_issue(
            _COVERAGE_ISSUE_TITLE
        )
        if existing_number:
            return  # already open; let humans triage it

        body_lines = [
            "DiagramLoop detected loops or ports in `src/` that aren't assigned",
            "to a functional area in `docs/arch/functional_areas.yml`.",
            "",
        ]
        if items["loops"]:
            body_lines.append("**Unassigned loops:**\n")
            body_lines.extend(f"- `{n}`" for n in items["loops"])
            body_lines.append("")
        if items["ports"]:
            body_lines.append("**Unassigned ports:**\n")
            body_lines.extend(f"- `{n}`" for n in items["ports"])
            body_lines.append("")
        body_lines.append(
            "Fix: edit `docs/arch/functional_areas.yml` and assign each item to "
            "the appropriate area's `loops:` or `ports:` list."
        )

        await self._pr_manager.create_issue(
            title=_COVERAGE_ISSUE_TITLE,
            body="\n".join(body_lines),
            labels=["hydraflow-find", "arch-knowledge"],
        )
