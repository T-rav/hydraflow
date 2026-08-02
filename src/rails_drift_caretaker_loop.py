"""RailsDriftCaretakerLoop — audits managed repos against their rails manifest.

Runtime enforcer for the rails manifest (ADR-0121, #10936). Periodically loads
each managed repo's ``rails.yaml``, observes its live state, and files one
deduped ``hydraflow-find`` drift issue **per repo per finding class** when the
repo diverges from what its manifest declares — the same shape as
``BranchProtectionAuditorLoop`` (ADR-0082) and the ADR-drift loop (ADR-0056).

Follows ADR-0029 (caretaker pattern) and ADR-0049 (kill-switch: first line of
``_do_work`` gates on ``enabled_cb`` then the static config flag).

Dedup: one key per ``rails_drift_caretaker:<repo>:<finding_class>`` — a repo
whose drift persists is not re-filed; when a finding class resolves, its open
issue is closed and the key cleared so a future recurrence re-files. Unknown /
future layer names are reported (logged) but never file an issue — they are
tolerated, not fatal (forward-compat with the Book-3 operator-agent pack).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps  # noqa: TCH001
from exception_classify import reraise_on_credit_or_bug
from loop_fitness import Confidence, FitnessContext, FitnessKind, LoopFitness
from rails_manifest import (
    FINDING_UNKNOWN_LAYER,
    ObservedRails,
    RailsDriftReport,
    compute_rails_drift,
    load_manifest,
)

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from dedup_store import DedupStore
    from ports import PRPort

logger = logging.getLogger("hydraflow.rails_drift_caretaker")

_KEY_PREFIX = "rails_drift_caretaker"
_DRIFT_LABELS = ["hydraflow-find", "hydraflow-rails-drift"]

# Layer → filesystem marker used by :func:`observe_rails`. Conservative and
# override-able; the concrete layer→marker mapping is v1 (ADR-0121) and may be
# refined as the template layers formalise.
_LAYER_MARKERS: dict[str, tuple[str, ...]] = {
    "universal": ("docs/adr/0044-hydraflow-principles.md",),
    "language_pack": ("pyproject.toml", "package.json", "go.mod", "Cargo.toml"),
    "domain_rails": ("docs/standards",),
}


def _dedup_key(repo: str, finding_class: str) -> str:
    return f"{_KEY_PREFIX}:{repo}:{finding_class}"


def _drift_title(repo: str, finding_class: str) -> str:
    return f"[rails-drift] {finding_class} on {repo}"


def _drift_body(report: RailsDriftReport, finding_class: str) -> str:
    findings = [f for f in report.findings if f.finding_class == finding_class]
    lines = [
        f"## Rails manifest drift — `{finding_class}`",
        "",
        f"`{report.repo}`'s live state diverges from its `rails.yaml` manifest "
        "(ADR-0121). Failing checks:",
        "",
    ]
    lines.extend(f"- `{f.check_id}` — {f.detail}" for f in findings)
    lines.extend(
        [
            "",
            "**Repair options:**",
            "1. Restore the declared layer/floor/script so the repo matches its "
            "manifest, OR",
            "2. If the change is intentional, update `rails.yaml` to reflect the "
            "new template surface (closes this issue on the next tick).",
            "",
            "_Filed by `rails_drift_caretaker` per ADR-0121 (#10936)._",
            "",
            "<!-- [hydraflow-auditor: source=RailsDriftCaretakerLoop] -->",
        ]
    )
    return "\n".join(lines)


class RailsDriftCaretakerLoop(BaseBackgroundLoop):
    """Files a drift issue when a managed repo diverges from its rails manifest."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        pr_manager: PRPort,
        dedup: DedupStore,
        deps: LoopDeps,
        auditor: Callable[[], Awaitable[list[RailsDriftReport]]],
    ) -> None:
        super().__init__(worker_name="rails_drift_caretaker", config=config, deps=deps)
        self._prs = pr_manager
        self._dedup = dedup
        self._auditor = auditor

    def _get_default_interval(self) -> int:
        return self._config.rails_drift_caretaker_interval

    def loop_fitness(self, ctx: FitnessContext) -> LoopFitness:
        # Like GateActivatorLoop / BranchProtectionAuditorLoop: files ONE
        # deduped, stable-titled issue per (repo, finding class) and CLOSES IT
        # ITSELF when the drift resolves. "Closed" reflects the loop's own
        # housekeeping, not human acceptance — there is no clean per-finding
        # acceptance signal — so report HOUSEKEEPING rather than counting
        # self-closures as accepted.
        return LoopFitness(
            worker_name=self._worker_name,
            kind=FitnessKind.HOUSEKEEPING,
            confidence=Confidence.INSUFFICIENT_DATA,
            timestamp=ctx.window_end,
        )

    async def _do_work(self) -> dict[str, Any] | None:  # noqa: PLR0911
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.rails_drift_caretaker_loop_enabled:
            return {"status": "config_disabled"}
        if self._config.dry_run:
            return None

        try:
            reports = await self._auditor()
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning("rails-drift audit failed", exc_info=True)
            return {"error": True}

        dedup = self._dedup.get()
        filed = 0
        deduped = 0
        resolved = 0
        for report in reports:
            if not report.has_manifest:
                # Repo carries no rails.yaml — unmanaged by the rails contract.
                continue
            unknown = report.tolerated_unknown_layers
            if unknown:
                logger.info(
                    "rails: tolerated unknown layer(s) on %s: %s (reported, not fatal)",
                    report.repo,
                    ", ".join(unknown),
                )
            f, d = await self._file_repo_drift(report, dedup)
            filed += f
            deduped += d
            resolved += await self._reconcile_resolved(report, dedup)

        self._dedup.set_all(dedup)
        status = "drift" if filed or deduped else "clean"
        return {
            "status": status,
            "filed": filed,
            "deduped": deduped,
            "resolved": resolved,
        }

    async def _file_repo_drift(
        self, report: RailsDriftReport, dedup: set[str]
    ) -> tuple[int, int]:
        """File one deduped issue per fatal finding class. Returns (filed, deduped)."""
        filed = 0
        deduped = 0
        classes = sorted({f.finding_class for f in report.fatal_findings})
        for finding_class in classes:
            key = _dedup_key(report.repo, finding_class)
            if key in dedup:
                deduped += 1
                continue
            try:
                issue = await self._prs.create_issue(
                    _drift_title(report.repo, finding_class),
                    _drift_body(report, finding_class),
                    labels=_DRIFT_LABELS,
                )
            except Exception as exc:
                reraise_on_credit_or_bug(exc)
                logger.warning("could not file rails-drift issue", exc_info=True)
                continue
            if issue == 0:
                logger.error(
                    "rails_drift_caretaker: create_issue returned 0 (sentinel) — "
                    "not tracking phantom issue; will retry next cycle"
                )
                continue
            dedup.add(key)
            filed += 1
        return filed, deduped

    async def _reconcile_resolved(
        self, report: RailsDriftReport, dedup: set[str]
    ) -> int:
        """Close + clear any tracked finding class for this repo that no longer
        drifts (#9359 issue-hygiene, mirroring branch-protection's clean path)."""
        active = {
            _dedup_key(report.repo, f.finding_class) for f in report.fatal_findings
        }
        prefix = f"{_KEY_PREFIX}:{report.repo}:"
        stale = {k for k in dedup if k.startswith(prefix) and k not in active}
        resolved = 0
        for key in stale:
            finding_class = key[len(prefix) :]
            title = _drift_title(report.repo, finding_class)
            existing = await self._prs.find_existing_issue(title)
            if existing:
                await self._prs.post_comment(
                    existing, "Rails manifest drift resolved — auto-closing."
                )
                await self._prs.close_issue(existing)
            dedup.discard(key)
            resolved += 1
        return resolved


# --------------------------------------------------------------------------- #
# Live observation + real-auditor builder                                      #
# --------------------------------------------------------------------------- #


def observe_rails(repo_root: Path, *, coverage: float | None = None) -> ObservedRails:
    """Observe a repo checkout's live rails state (v1 marker-based detection).

    Layer presence is inferred from marker files (:data:`_LAYER_MARKERS`);
    domain gate scripts are checked under ``scripts/``. ``coverage`` is passed
    through when known (else ``None`` — the floor is then not evaluated).
    """
    present: set[str] = set()
    for layer, markers in _LAYER_MARKERS.items():
        if any((repo_root / marker).exists() for marker in markers):
            present.add(layer)
    scripts_dir = repo_root / "scripts"
    present_scripts: set[str] = set()
    if scripts_dir.is_dir():
        present_scripts = {p.name for p in scripts_dir.iterdir()}
    return ObservedRails(
        present_layers=frozenset(present),
        coverage=coverage,
        present_gate_scripts=frozenset(present_scripts),
    )


def audit_repo_rails(repo: str, repo_root: Path) -> RailsDriftReport:
    """Audit one managed repo's checkout against its ``rails.yaml``.

    Returns a report with ``has_manifest=False`` when the repo carries no
    manifest (unmanaged by the rails contract) — the loop skips those.
    """
    manifest = load_manifest(repo_root / "rails.yaml")
    if manifest is None:
        return RailsDriftReport(repo=repo, findings=(), has_manifest=False)
    observed = observe_rails(repo_root)
    return compute_rails_drift(manifest, observed, repo=repo)


def build_rails_auditor(
    config: HydraFlowConfig,
) -> Callable[[], Awaitable[list[RailsDriftReport]]]:
    """Build the real auditor: audit the factory's managed repo checkout.

    Single-repo today (``config.repo`` at ``config.repo_root``); returns a
    one-element list so the loop's per-repo shape generalises to multi-repo.
    Offloaded to a thread — filesystem reads must not stall the event loop.
    """
    import asyncio  # noqa: PLC0415

    async def _audit() -> list[RailsDriftReport]:
        report = await asyncio.to_thread(
            audit_repo_rails, config.repo, config.repo_root
        )
        return [report]

    return _audit


# Re-export so callers can group by the tolerated class without importing the
# manifest module directly.
__all__ = [
    "FINDING_UNKNOWN_LAYER",
    "RailsDriftCaretakerLoop",
    "audit_repo_rails",
    "build_rails_auditor",
    "observe_rails",
]
