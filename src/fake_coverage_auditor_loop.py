"""FakeCoverageAuditorLoop — weekly un-cassetted-method detector.

Spec: `docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md`
§4.7. Introspects fake classes under `src/mockworld/fakes/` via
``ast.parse`` and compares two method sets to their coverage sources:

- ``adapter-surface`` — public non-private methods. Covered by a
  cassette under ``tests/trust/contracts/cassettes/<adapter>/`` whose
  ``input.command`` names the method.
- ``test-helper`` — helpers the scenarios drive (``script_*``,
  ``fail_service``, ``heal_service``, ``set_state``). Covered by a
  scenario test under ``tests/scenarios/`` that calls the helper.

Files ``find_label`` + ``fake_coverage_gap_label`` + one of
``adapter_surface_label`` | ``test_helper_label`` per **rollup** —
one issue per ``(fake_class, gap_kind)`` listing all uncovered methods
in the body (issue #8986). Subsequent ticks update the body via
``PRPort.update_issue_body``: append newly-uncovered methods, strike
through methods that gained coverage. Escalates after 3 attempts at the
rollup granularity to ``hitl_escalation_label`` + ``fake_coverage_stuck_label``.
All five label fields are registered in ``HYDRAFLOW_LABELS`` so
``make ensure-labels`` provisions them.
"""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

import yaml

from base_background_loop import BaseBackgroundLoop, LoopDeps  # noqa: TCH001
from models import WorkCycleResult  # noqa: TCH001

if TYPE_CHECKING:
    from pathlib import Path

    from config import HydraFlowConfig
    from dedup_store import DedupStore
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.fake_coverage_auditor_loop")

_MAX_ATTEMPTS = 3
_HELPER_PREFIXES = ("script_",)
_HELPER_NAMES = frozenset(
    {
        "fail_service",
        "heal_service",
        "set_state",
        "reject_next_push",
        "set_corrupted_config",
        "active_worktrees",
    }
)

# Per-class overrides: methods that don't match the generic prefix/name rules
# but are test-only helpers rather than real adapter-surface methods.
_FAKE_HELPER_OVERRIDES: dict[tuple[str, str], str] = {
    ("FakeGitHub", "clear_rate_limit"): "test-helper",
    ("FakeGitHub", "set_rate_limit_mode"): "test-helper",
    # FakeDocker's single-shot fault-injection helpers have no real-adapter
    # counterpart (the real container runner has no fail_next/clear_fault), so
    # no cassette can record them — mirror the FakeGitHub carve-out (#9177).
    ("FakeDocker", "clear_fault"): "test-helper",
    ("FakeDocker", "fail_next"): "test-helper",
}


def _is_helper(name: str, class_name: str = "") -> bool:
    if class_name and (class_name, name) in _FAKE_HELPER_OVERRIDES:
        return True
    return any(name.startswith(p) for p in _HELPER_PREFIXES) or name in _HELPER_NAMES


def catalog_fake_methods(fake_dir: Path) -> dict[str, dict[str, list[str]]]:
    """AST-scan ``fake_dir/*.py`` for classes starting with ``Fake``.

    Returns::

        {
          "FakeGitHub": {
            "adapter-surface": ["create_issue", "close_issue", ...],
            "test-helper":     ["script_ci", "fail_service", ...],
          },
          ...
        }
    """
    catalog: dict[str, dict[str, list[str]]] = {}
    if not fake_dir.exists():
        return catalog
    for path in sorted(fake_dir.glob("*.py")):
        if path.name.startswith("test_") or path.name == "__init__.py":
            continue
        try:
            tree = ast.parse(path.read_text(), filename=str(path))
        except SyntaxError:
            logger.debug("syntax error parsing %s", path)
            continue
        for node in ast.iter_child_nodes(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not node.name.startswith("Fake"):
                continue
            surface: list[str] = []
            helpers: list[str] = []
            for child in node.body:
                if not isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                name = child.name
                if name.startswith("_"):
                    continue
                if _is_helper(name, node.name):
                    helpers.append(name)
                else:
                    surface.append(name)
            catalog[node.name] = {
                "adapter-surface": sorted(surface),
                "test-helper": sorted(helpers),
            }
    return catalog


def catalog_cassette_methods(cassette_dir: Path) -> set[str]:
    """Return the set of real-adapter methods recorded under ``cassette_dir``.

    Each cassette is a YAML file with an ``input.command`` field naming
    the method invoked (per §4.2 cassette schema, landed in
    `src/contracts/_schema.py`).
    """
    methods: set[str] = set()
    if not cassette_dir.exists():
        return methods
    for path in cassette_dir.rglob("*.yaml"):
        try:
            data = yaml.safe_load(path.read_text())
        except yaml.YAMLError:
            continue
        if not isinstance(data, dict):
            continue
        inp = data.get("input")
        if not isinstance(inp, dict):
            continue
        cmd = inp.get("command")
        if isinstance(cmd, str):
            methods.add(cmd)
    return methods


# Map from fake class name → cassette sub-directory.
_FAKE_TO_CASSETTE_DIR: dict[str, str] = {
    "FakeGitHub": "github",
    "FakeDocker": "docker",
    "FakeGit": "git",
    "FakeBeads": "beads",
    "FakeSentry": "sentry",
    "FakeHTTP": "http",
    "FakeSubprocessRunner": "subprocess",
    "FakeFS": "fs",
    "FakeLLM": "llm",
}


class FakeCoverageAuditorLoop(BaseBackgroundLoop):
    """Weekly fake-surface coverage auditor (spec §4.7)."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        state: StateTracker,
        pr_manager: PRManager,
        dedup: DedupStore,
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="fake_coverage_auditor",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._state = state
        self._pr = pr_manager
        self._dedup = dedup
        # #8786 Phase 9 — when set, the loop runs the cassette retirement
        # audit each tick. Injected after construction by service_registry
        # so the callback can point at LiveCorpusReplayLoop's
        # ``registered_shapes`` (which is built later in the wiring).
        self._retirement_keys_cb: Callable[[], set[tuple[str, str]]] | None = None

    def set_retirement_keys_cb(
        self, cb: Callable[[], set[tuple[str, str]]] | None
    ) -> None:
        """Install (or clear with None) the dispatcher-key callback for the
        cassette retirement audit. Idempotent."""
        self._retirement_keys_cb = cb

    def _get_default_interval(self) -> int:
        return self._config.fake_coverage_auditor_interval

    async def _grep_scenario_for_helper(self, helper: str) -> bool:
        """Return True iff ``tests/scenarios/`` contains a call to ``helper``."""
        repo = self._config.repo_root
        scenario_dir = repo / "tests" / "scenarios"
        if not scenario_dir.exists():
            return False
        cmd = [
            "rg",
            "--type=py",
            "-l",
            "--fixed-strings",
            f"{helper}(",
            str(scenario_dir),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        # rg exits 0 on match, 1 on no-match, 2+ on error.
        return proc.returncode == 0 and bool(stdout.strip())

    def _render_surface_body(
        self,
        fake: str,
        uncovered: list[str],
        recovered: list[str],
    ) -> str:
        """Build the rollup-issue body for an adapter-surface gap.

        ``uncovered`` is the live list of methods missing cassettes;
        ``recovered`` is methods that previously appeared in the body but
        have since gained a cassette — rendered as strikethrough so the
        history of the rollup is visible to a human triager.
        """
        subdir = _FAKE_TO_CASSETTE_DIR.get(fake, "?")
        lines = [
            "## Fake coverage gap — adapter surface",
            "",
            f"Fake class `{fake}` exposes public methods with no matching "
            f"cassette under `tests/trust/contracts/cassettes/{subdir}/`.",
            "",
            f"**Uncovered methods ({len(uncovered)}):**",
            "",
        ]
        if uncovered:
            lines.extend(f"- `{method}`" for method in sorted(uncovered))
        else:
            lines.append("_(none — auditor should close this issue on next tick)_")
        if recovered:
            lines.extend(
                [
                    "",
                    "**Recently recovered (gained coverage):**",
                    "",
                ]
            )
            lines.extend(f"- ~~`{method}`~~" for method in sorted(recovered))
        lines.extend(
            [
                "",
                "**Repair:** record a cassette exercising each real-adapter "
                "counterpart and commit. Spec §4.7; filed by "
                "`fake_coverage_auditor` (#8986 rollup).",
                "",
                "<!-- [hydraflow-auditor: source=FakeCoverageAuditorLoop] -->",
            ]
        )
        return "\n".join(lines)

    def _render_helper_body(
        self,
        fake: str,
        uncovered: list[str],
        recovered: list[str],
    ) -> str:
        """Build the rollup-issue body for a test-helper gap."""
        lines = [
            "## Fake coverage gap — test helper",
            "",
            f"Fake class `{fake}` exposes helpers that no scenario under "
            f"`tests/scenarios/` invokes (grep-based search).",
            "",
            f"**Unexercised helpers ({len(uncovered)}):**",
            "",
        ]
        if uncovered:
            lines.extend(f"- `{method}`" for method in sorted(uncovered))
        else:
            lines.append("_(none — auditor should close this issue on next tick)_")
        if recovered:
            lines.extend(
                [
                    "",
                    "**Recently recovered (gained a scenario caller):**",
                    "",
                ]
            )
            lines.extend(f"- ~~`{method}`~~" for method in sorted(recovered))
        lines.extend(
            [
                "",
                "**Repair:** add a scenario that calls each helper so it is "
                "part of the working contract. Spec §4.7; filed by "
                "`fake_coverage_auditor` (#8986 rollup).",
                "",
                "<!-- [hydraflow-auditor: source=FakeCoverageAuditorLoop] -->",
            ]
        )
        return "\n".join(lines)

    async def _file_surface_gap(
        self, fake: str, uncovered: list[str], recovered: list[str] | None = None
    ) -> int:
        """File the adapter-surface rollup issue for ``fake``. (#8986 rollup.)"""
        title = f"Fake coverage gap: {fake} adapter surface ({len(uncovered)} methods)"
        body = self._render_surface_body(fake, uncovered, recovered or [])
        return await self._pr.create_issue(
            title,
            body,
            [
                *self._config.find_label,
                *self._config.fake_coverage_gap_label,
                *self._config.adapter_surface_label,
            ],
        )

    async def _file_helper_gap(
        self, fake: str, uncovered: list[str], recovered: list[str] | None = None
    ) -> int:
        """File the test-helper rollup issue for ``fake``. (#8986 rollup.)"""
        title = f"Fake coverage gap: {fake} test helpers ({len(uncovered)} methods)"
        body = self._render_helper_body(fake, uncovered, recovered or [])
        return await self._pr.create_issue(
            title,
            body,
            [
                *self._config.find_label,
                *self._config.fake_coverage_gap_label,
                *self._config.test_helper_label,
            ],
        )

    async def _file_escalation(self, key: str, attempts: int) -> int:
        title = f"HITL: fake coverage gap {key} unresolved after {attempts}"
        body = (
            f"`fake_coverage_auditor` has re-filed the `{key}` gap "
            f"{attempts} times without closure. Human review needed.\n\n"
            f"_Spec §3.2: closing this issue clears the dedup key._"
        )
        return await self._pr.create_issue(
            title,
            body,
            [
                *self._config.hitl_escalation_label,
                *self._config.fake_coverage_stuck_label,
            ],
        )

    async def _reconcile_closed_escalations(self) -> None:
        """Clear dedup keys for closed fake-coverage-stuck escalations.

        Escalations are now filed at rollup granularity (``{Fake}:{kind}``),
        so the title-substring match works against the new key shape. Old
        per-method dedup keys (pre-#8986) carry a ``.method`` segment and
        will simply not match any open escalation title — they age out
        silently on the next non-escalated tick.
        """
        cmd = [
            "gh",
            "issue",
            "list",
            "--repo",
            self._config.repo,
            "--state",
            "closed",
        ]
        for label in (
            *self._config.hitl_escalation_label,
            *self._config.fake_coverage_stuck_label,
        ):
            cmd.extend(["--label", label])
        cmd.extend(
            [
                "--author",
                "@me",
                "--limit",
                "100",
                "--json",
                "title",
            ]
        )
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return
        try:
            closed = json.loads(stdout.decode() or "[]")
        except json.JSONDecodeError:
            return
        current = self._dedup.get()
        keep = set(current)
        for issue in closed:
            title = issue.get("title", "")
            for key in list(keep):
                if (
                    key.startswith("fake_coverage_auditor:")
                    and key.split(":", 1)[1] in title
                ):
                    keep.discard(key)
                    self._state.clear_fake_coverage_attempts(key.split(":", 1)[1])
        if keep != current:
            self._dedup.set_all(keep)

    async def _list_open_rollup_titles(self) -> set[str]:
        """Return the set of titles of currently-open rollup issues we filed.

        Used to detect "issue closed-by-human between ticks" so we don't
        leak a stale rollup-issue-number in state. We look up open issues
        with ``fake-coverage-gap`` label and snapshot their titles; if the
        title we expect for ``(fake, kind)`` is missing, treat the rollup
        as closed and re-file on this tick (zombie-state guard).
        """
        cmd = [
            "gh",
            "issue",
            "list",
            "--repo",
            self._config.repo,
            "--state",
            "open",
            "--author",
            "@me",
            "--limit",
            "200",
            "--json",
            "title",
        ]
        for label in self._config.fake_coverage_gap_label:
            cmd.extend(["--label", label])
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode != 0:
                return set()
            data = json.loads(stdout.decode() or "[]")
        except (OSError, json.JSONDecodeError):
            return set()
        return {entry.get("title", "") for entry in data}

    def _rollup_title_prefix(self, fake: str, kind: str) -> str:
        """Stable prefix for matching an existing rollup title regardless of
        the trailing ``(N methods)`` count."""
        if kind == "adapter-surface":
            return f"Fake coverage gap: {fake} adapter surface"
        return f"Fake coverage gap: {fake} test helpers"

    async def _do_work(self) -> WorkCycleResult:
        """Scan fakes, compare to cassettes + scenario grep, file rollup gaps.

        Per #8986 the loop files **one rollup issue per ``(fake, kind)``**
        instead of one issue per ``(fake, method)`` — drastically reducing
        triage cost. Subsequent ticks update the rollup body via
        ``PRPort.update_issue_body``. 3-strikes escalation moves to
        ``(fake, kind)`` granularity.
        """
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.fake_coverage_auditor_loop_enabled:
            return {"status": "config_disabled"}

        t0 = time.perf_counter()
        await self._reconcile_closed_escalations()

        repo = self._config.repo_root
        fake_dir = repo / "src" / "mockworld" / "fakes"
        cassette_root = repo / "tests" / "trust" / "contracts" / "cassettes"
        catalog = catalog_fake_methods(fake_dir)
        if not catalog:
            return {"status": "no_fakes", "filed": 0}

        # Snapshot of open rollup-issue titles — used to detect
        # closed-by-human rollups and re-file cleanly (zombie-state guard).
        open_titles = await self._list_open_rollup_titles()
        # Methods we previously reported but now have coverage — rendered
        # as strikethrough so the rollup body shows the trajectory.
        last_known = self._state.get_fake_coverage_last_known()

        filed = 0
        updated = 0
        escalated = 0
        dedup = self._dedup.get()
        all_known: dict[str, list[str]] = {}
        for fake, sets in catalog.items():
            helper_methods = sets["test-helper"]
            # Adapter-surface (cassette) auditing only applies to fakes
            # explicitly registered in ``_FAKE_TO_CASSETTE_DIR`` — the fakes of
            # external adapters whose real I/O can be recorded. Internal-port
            # fakes (a clock, in-memory stores, span-assertion helpers) have no
            # recordable counterpart, so no cassette can ever cover them.
            # Registration is the deliberate opt-in; an unmapped fake is skipped
            # rather than audited against the cassette ROOT (the old
            # ``.get(fake, "")`` fallback), which flagged every method as a
            # false gap. Test-helper (scenario) coverage still applies to all
            # fakes below.
            if fake in _FAKE_TO_CASSETTE_DIR:
                cassette_subdir = cassette_root / _FAKE_TO_CASSETTE_DIR[fake]
                cassetted = catalog_cassette_methods(cassette_subdir)
                surface_methods = sets["adapter-surface"]
            else:
                cassetted = set()
                surface_methods = []

            covered: list[str] = []
            uncovered_surface: list[str] = []
            for method in surface_methods:
                if method in cassetted:
                    covered.append(method)
                else:
                    uncovered_surface.append(method)

            uncovered_helpers: list[str] = []
            for method in helper_methods:
                if await self._grep_scenario_for_helper(method):
                    covered.append(method)
                else:
                    uncovered_helpers.append(method)

            # Strikethrough = methods that were uncovered last tick but
            # are now covered. ``last_known`` persists last tick's
            # uncovered set under sentinel keys ``__uncovered__:{fake}:{kind}``.
            prior_uncovered_surface = set(
                last_known.get(f"__uncovered__:{fake}:adapter-surface", [])
            )
            prior_uncovered_helpers = set(
                last_known.get(f"__uncovered__:{fake}:test-helper", [])
            )
            recovered_surface = sorted(prior_uncovered_surface - set(uncovered_surface))
            recovered_helpers = sorted(prior_uncovered_helpers - set(uncovered_helpers))

            # --- adapter-surface rollup ---
            if uncovered_surface:
                action, _did_file = await self._handle_rollup(
                    fake=fake,
                    kind="adapter-surface",
                    uncovered=uncovered_surface,
                    recovered=recovered_surface,
                    open_titles=open_titles,
                    dedup=dedup,
                )
                if action == "escalated":
                    escalated += 1
                elif action == "filed":
                    filed += 1
                elif action == "updated":
                    updated += 1
            else:
                # Gap closed — clear attempts + drop the rollup mapping so
                # the next regression re-files cleanly.
                await self._clear_rollup_state(
                    fake, "adapter-surface", dedup, recovered=recovered_surface
                )

            # --- test-helper rollup ---
            if uncovered_helpers:
                action, _did_file = await self._handle_rollup(
                    fake=fake,
                    kind="test-helper",
                    uncovered=uncovered_helpers,
                    recovered=recovered_helpers,
                    open_titles=open_titles,
                    dedup=dedup,
                )
                if action == "escalated":
                    escalated += 1
                elif action == "filed":
                    filed += 1
                elif action == "updated":
                    updated += 1
            else:
                await self._clear_rollup_state(
                    fake, "test-helper", dedup, recovered=recovered_helpers
                )

            all_known[fake] = sorted(covered)
            # Persist this tick's uncovered set under sentinel keys so the
            # next tick can compute strikethrough.
            all_known[f"__uncovered__:{fake}:adapter-surface"] = sorted(
                uncovered_surface
            )
            all_known[f"__uncovered__:{fake}:test-helper"] = sorted(uncovered_helpers)

        self._state.set_fake_coverage_last_known(all_known)

        # #8786 Phase 9 — cassette retirement audit. Runs each tick;
        # ``_retirement_keys_cb`` is wired by service_registry from
        # LiveCorpusReplayLoop's registered dispatcher set.
        retirement_filed = 0
        if self._retirement_keys_cb is not None:
            retirement_filed = await self._audit_retirement(cassette_root)

        self._emit_trace(t0, fakes_seen=len(catalog))
        return {
            "status": "ok",
            "filed": filed,
            "updated": updated,
            "escalated": escalated,
            "fakes_seen": len(catalog),
            "retirement_filed": retirement_filed,
        }

    async def _handle_rollup(
        self,
        *,
        fake: str,
        kind: str,
        uncovered: list[str],
        recovered: list[str],
        open_titles: set[str],
        dedup: set[str],
    ) -> tuple[str, bool]:
        """Drive the per-``(fake, kind)`` rollup: file/update or escalate.

        Returns ``(action, did_file)`` where ``action`` is one of
        ``"filed"``, ``"updated"``, ``"escalated"``, or ``"skipped"``.
        """
        # Shared ``{fake}:{kind}`` key for the attempt counter and the
        # rollup-issue-number mapping; the dedup set uses a namespaced
        # variant. Three independent keys, one logical identity.
        key = f"{fake}:{kind}"
        dedup_key = f"fake_coverage_auditor:{fake}:{kind}"

        # If we already have a tracked open rollup, *always* update it —
        # subsequent ticks must keep the body fresh even though the
        # dedup key is set.
        tracked_number = self._state.get_fake_coverage_rollup_issue(key)
        prefix = self._rollup_title_prefix(fake, kind)
        still_open = any(title.startswith(prefix) for title in open_titles)
        if tracked_number and still_open:
            if kind == "adapter-surface":
                body = self._render_surface_body(fake, uncovered, recovered)
            else:
                body = self._render_helper_body(fake, uncovered, recovered)
            await self._pr.update_issue_body(tracked_number, body)
            # Bump the attempt counter once per tick the gap remains open
            # so 3-strikes escalation still fires. Fire escalation exactly
            # once — when the counter crosses ``_MAX_ATTEMPTS`` — not every
            # subsequent tick (which would file a fresh HITL issue per
            # tick until a human acts).
            attempts = self._state.inc_fake_coverage_attempts(key)
            if attempts == _MAX_ATTEMPTS:
                await self._file_escalation(key, attempts)
                return ("escalated", False)
            return ("updated", False)

        # Closed-by-human zombie: drop the stale state and re-file fresh.
        if tracked_number and not still_open:
            self._state.clear_fake_coverage_rollup_issue(key)
            # Also reset the attempt counter so the human's "close" is
            # treated as a real reset, not a partial step toward escalation.
            self._state.clear_fake_coverage_attempts(key)
            dedup.discard(dedup_key)
            self._dedup.set_all(dedup)

        # No tracked rollup yet on this tick. Either it's a brand-new gap
        # or the dedup key is set from a prior tick where we already filed
        # but lost the number (shouldn't happen post-#8986, but be defensive).
        if dedup_key in dedup and not tracked_number:
            # Defensive: dedup key present but no tracked issue number.
            # Treat as fresh file so the rollup gets re-established.
            dedup.discard(dedup_key)
            self._dedup.set_all(dedup)

        attempts = self._state.inc_fake_coverage_attempts(key)
        if attempts == _MAX_ATTEMPTS:
            # Fire once when the counter crosses the threshold. Subsequent
            # ticks fall through to a fresh rollup file via the path below
            # (or skip if dedup_key was set earlier), which avoids the
            # tick-per-tick escalation storm.
            await self._file_escalation(key, attempts)
            dedup.add(dedup_key)
            self._dedup.set_all(dedup)
            return ("escalated", False)

        if kind == "adapter-surface":
            number = await self._file_surface_gap(fake, uncovered, recovered)
        else:
            number = await self._file_helper_gap(fake, uncovered, recovered)
        if number:
            self._state.set_fake_coverage_rollup_issue(key, number)
        dedup.add(dedup_key)
        self._dedup.set_all(dedup)
        return ("filed", True)

    async def _clear_rollup_state(
        self,
        fake: str,
        kind: str,
        dedup: set[str],
        recovered: list[str] | None = None,
    ) -> None:
        """Reset rollup tracking when the gap closes (no uncovered methods).

        Drops the attempt counter, dedup key, and rollup-issue mapping so
        a future regression re-files cleanly. When the previous tick had
        an actual gap (``recovered`` is non-empty) AND a rollup issue is
        tracked, repaint the body with the "all covered" view first so
        humans looking at the open issue see the resolution rather than
        a stale list of methods. The issue itself is left open for humans
        to close.
        """
        key = f"{fake}:{kind}"  # shared key for attempts + rollup mapping
        dedup_key = f"fake_coverage_auditor:{fake}:{kind}"
        tracked_number = self._state.get_fake_coverage_rollup_issue(key)
        if tracked_number and recovered:
            if kind == "adapter-surface":
                body = self._render_surface_body(fake, [], recovered)
            else:
                body = self._render_helper_body(fake, [], recovered)
            await self._pr.update_issue_body(tracked_number, body)
        self._state.clear_fake_coverage_attempts(key)
        self._state.clear_fake_coverage_rollup_issue(key)
        if dedup_key in dedup:
            dedup.discard(dedup_key)
            self._dedup.set_all(dedup)

    async def _audit_retirement(self, cassette_root: Path) -> int:
        """Find baseline_only cassettes covered by live dispatchers; file
        one issue per batch (dedup'd on candidate set) flagging them as
        eligible for removal.

        Returns the number of issues filed this tick (0 or 1).
        """
        from contracts.retirement import (  # noqa: PLC0415
            find_retirement_candidates,
            format_candidates_for_issue,
        )

        cb = self._retirement_keys_cb
        if cb is None:
            return 0
        try:
            keys = cb()
        except Exception:  # noqa: BLE001 — audit must not crash the loop
            logger.exception("retirement audit: callback raised; skipping tick")
            return 0
        candidates = find_retirement_candidates(cassette_root, keys)
        if not candidates:
            return 0

        dedup_key = (
            f"cassette_retirement:{','.join(sorted(c.path.name for c in candidates))}"
        )
        if dedup_key in self._dedup.get():
            return 0

        title = (
            f"Cassette retirement: {len(candidates)} hand-authored baseline(s) "
            f"now covered by live dispatchers"
        )
        body = format_candidates_for_issue(candidates)
        labels = [
            *self._config.find_label,
            "cassette-retirement-ready",
        ]
        try:
            await self._pr.create_issue(title, body, labels)
        except Exception:  # noqa: BLE001 — issue filing failure ≠ loop failure
            logger.exception("retirement audit: create_issue failed")
            return 0
        seen = self._dedup.get()
        seen.add(dedup_key)
        self._dedup.set_all(seen)
        return 1

    def _emit_trace(self, t0: float, *, fakes_seen: int) -> None:
        try:
            from trace_collector import emit_loop_subprocess_trace  # noqa: PLC0415
        except ImportError:
            return
        duration_ms = int((time.perf_counter() - t0) * 1000)
        emit_loop_subprocess_trace(
            loop=self._worker_name,
            command=["ast.parse", "fakes/"],
            exit_code=0,
            duration_ms=duration_ms,
            stderr_excerpt=f"fakes_seen={fakes_seen}",
        )
