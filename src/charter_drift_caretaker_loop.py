"""CharterDriftCaretakerLoop — audits managed repos against their charter.

Runtime enforcer for the repo charter (``charter.yaml``, #11748; ADR-0121 as
amended, ADR-0143). Periodically loads each managed repo's charter, observes
its live state, and files one deduped ``hydraflow-find`` drift issue **per
repo per finding class** when the repo diverges from what its charter
declares — the same shape as ``BranchProtectionAuditorLoop`` (ADR-0082) and
the ADR-drift loop (ADR-0056).

Follows ADR-0029 (caretaker pattern) and ADR-0049 (kill-switch: first line of
``_do_work`` gates on ``enabled_cb`` then the static config flag).

Dedup: one key per ``charter_drift_caretaker:<repo>:<finding_class>`` — a repo
whose drift persists is not re-filed; when a finding class resolves, its open
issue is closed and the key cleared so a future recurrence re-files.
Non-fatal findings (unknown layer, unknown standard id, a legacy
``rails.yaml`` fallback) are reported (logged) but never file an issue.

This loop is the *act* half of ADR-0143 Ruling 4. The *decide* half —
:func:`~charter.compute_charter_drift` — is pure over the charter and the
observation; every filesystem read lives here, in :func:`observe_repo`.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps  # noqa: TCH001
from charter import (
    Charter,
    CharterDriftReport,
    ObservedRepo,
    compute_charter_drift,
    load_charter,
    standard_ids_under,
)
from exception_classify import reraise_on_credit_or_bug
from loop_fitness import Confidence, FitnessContext, FitnessKind, LoopFitness
from package_resources import checkout_root

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from dedup_store import DedupStore
    from ports import PRPort

logger = logging.getLogger("hydraflow.charter_drift_caretaker")

_KEY_PREFIX = "charter_drift_caretaker"
_DRIFT_LABELS = ["hydraflow-find", "hydraflow-charter-drift"]

# Layer → filesystem marker used by :func:`observe_repo`. Conservative and
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
    return f"[charter-drift] {finding_class} on {repo}"


def _drift_body(report: CharterDriftReport, finding_class: str) -> str:
    findings = [f for f in report.findings if f.finding_class == finding_class]
    lines = [
        f"## Charter drift — `{finding_class}`",
        "",
        f"`{report.repo}`'s live state diverges from its `charter.yaml` "
        "(ADR-0121 as amended by #11748). Failing checks:",
        "",
    ]
    lines.extend(f"- `{f.check_id}` — {f.detail}" for f in findings)
    lines.extend(
        [
            "",
            "**Repair options:**",
            "1. Restore the declared standard/artifact/layer/floor/script so the "
            "repo matches its charter, OR",
            "2. If the change is intentional, update `charter.yaml` to reflect "
            "the new surface (closes this issue on the next tick).",
            "",
            "_Filed by `charter_drift_caretaker` per ADR-0121 / ADR-0143 "
            "(#11748)._",
            "",
            "<!-- [hydraflow-auditor: source=CharterDriftCaretakerLoop] -->",
        ]
    )
    return "\n".join(lines)


class CharterDriftCaretakerLoop(BaseBackgroundLoop):
    """Files a drift issue when a managed repo diverges from its charter."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        pr_manager: PRPort,
        dedup: DedupStore,
        deps: LoopDeps,
        auditor: Callable[[], Awaitable[list[CharterDriftReport]]],
    ) -> None:
        super().__init__(
            worker_name="charter_drift_caretaker", config=config, deps=deps
        )
        self._prs = pr_manager
        self._dedup = dedup
        self._auditor = auditor

    def _get_default_interval(self) -> int:
        return self._config.charter_drift_caretaker_interval

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
        if not self._config.charter_drift_caretaker_loop_enabled:
            return {"status": "config_disabled"}
        if self._config.dry_run:
            return None

        try:
            reports = await self._auditor()
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning("charter-drift audit failed", exc_info=True)
            return {"error": True}

        dedup = self._dedup.get()
        filed = 0
        deduped = 0
        resolved = 0
        for report in reports:
            if not report.has_charter:
                # Repo carries no charter.yaml — ungoverned by the contract.
                continue
            tolerated = report.tolerated_findings
            if tolerated:
                logger.info(
                    "charter: tolerated finding(s) on %s: %s (reported, not fatal)",
                    report.repo,
                    ", ".join(f.check_id for f in tolerated),
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
        self, report: CharterDriftReport, dedup: set[str]
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
                logger.warning("could not file charter-drift issue", exc_info=True)
                continue
            if issue == 0:
                logger.error(
                    "charter_drift_caretaker: create_issue returned 0 (sentinel) — "
                    "not tracking phantom issue; will retry next cycle"
                )
                continue
            dedup.add(key)
            filed += 1
        return filed, deduped

    async def _reconcile_resolved(
        self, report: CharterDriftReport, dedup: set[str]
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
                    existing, "Charter drift resolved — auto-closing."
                )
                await self._prs.close_issue(existing)
            dedup.discard(key)
            resolved += 1
        return resolved


# --------------------------------------------------------------------------- #
# Live observation + real-auditor builder                                      #
# --------------------------------------------------------------------------- #


def shipped_standard_ids() -> frozenset[str] | None:
    """Standard ids HydraFlow itself ships, or ``None`` when unknowable.

    Enumerated from the HydraFlow checkout rather than hardcoded, so adding
    ``docs/standards/<id>/`` is the only step needed to make an id
    recognisable. ``None`` — no checkout, or a checkout with no
    ``docs/standards/`` — is deliberately *not* an empty set: an empty
    registry would silently downgrade every ``missing-standard`` to a
    tolerated ``unknown-standard``, and the drift check would read as
    coverage while checking nothing. :func:`~charter.compute_charter_drift`
    turns ``None`` into a fatal ``uncheckable-charter`` finding instead.
    """
    root = checkout_root()
    if root is None:
        return None
    ids = standard_ids_under(root)
    return ids or None


def observe_repo(
    repo_root: Path,
    charter: Charter,
    *,
    coverage: float | None = None,
) -> ObservedRepo:
    """Observe a repo checkout's live state against what *charter* declares.

    This is the only side of the drift check that touches the filesystem
    (ADR-0143 Ruling 5). Layer presence is inferred from marker files
    (:data:`_LAYER_MARKERS`); domain gate scripts are checked under
    ``scripts/``; standard ids are the directories under ``docs/standards/``;
    required artifacts are resolved as paths relative to the repo root.
    ``coverage`` is passed through when known (else ``None`` — the floor is
    then not evaluated).
    """
    present: set[str] = set()
    for layer, markers in _LAYER_MARKERS.items():
        if any((repo_root / marker).exists() for marker in markers):
            present.add(layer)

    scripts_dir = repo_root / "scripts"
    present_scripts: set[str] = set()
    if scripts_dir.is_dir():
        present_scripts = {p.name for p in scripts_dir.iterdir()}

    present_standards = standard_ids_under(repo_root)
    shipped = shipped_standard_ids()
    known = None if shipped is None else shipped | present_standards

    present_artifacts = frozenset(
        path for path in charter.artifacts.required if (repo_root / path).exists()
    )

    return ObservedRepo(
        present_layers=frozenset(present),
        coverage=coverage,
        present_gate_scripts=frozenset(present_scripts),
        present_standards=present_standards,
        present_artifacts=present_artifacts,
        known_standards=known,
    )


def audit_repo_charter(repo: str, repo_root: Path) -> CharterDriftReport:
    """Audit one managed repo's checkout against its ``charter.yaml``.

    Returns a report with ``has_charter=False`` when the repo carries no
    charter (and no legacy ``rails.yaml``) — the loop skips those.
    """
    charter = load_charter(repo_root)
    if charter is None:
        return CharterDriftReport(repo=repo, findings=(), has_charter=False)
    observed = observe_repo(repo_root, charter)
    return compute_charter_drift(charter, observed, repo=repo)


def build_charter_auditor(
    config: HydraFlowConfig,
) -> Callable[[], Awaitable[list[CharterDriftReport]]]:
    """Build the real auditor: audit the factory's managed repo checkout.

    Single-repo today (``config.repo`` at ``config.repo_root``); returns a
    one-element list so the loop's per-repo shape generalises to multi-repo.
    Offloaded to a thread — filesystem reads must not stall the event loop.
    """
    import asyncio  # noqa: PLC0415

    async def _audit() -> list[CharterDriftReport]:
        report = await asyncio.to_thread(
            audit_repo_charter, config.repo, config.repo_root
        )
        return [report]

    return _audit


__all__ = [
    "CharterDriftCaretakerLoop",
    "audit_repo_charter",
    "build_charter_auditor",
    "observe_repo",
    "shipped_standard_ids",
]
