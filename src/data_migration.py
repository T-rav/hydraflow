"""One-time, idempotent migration of legacy flat per-repo stores (ADR-0021 D2).

Historically several per-repo operational stores resolved via
``config.data_path(...)`` — i.e. under the flat ``data_root``. That was safe
under the original *process-per-repo* model (each process had its own
``HYDRAFLOW_HOME`` → its own ``data_root``). Under the multi-repo dashboard
model a single host process holds a registry of repo runtimes that share one
``data_root``, so those flat stores collide across repos.

This module relocates the affected stores into the repo-scoped layout
(``data_root/<repo_slug>/...``), matching the migration mechanism already used
for ``state.json``/``events.jsonl``/``sessions.jsonl`` in
``config._resolve_repo_scoped_paths``.

**Host-only.** Call once at host startup with the *host* config (see
``server._run``). The legacy flat data was written by the host process before
the scoped layout existed (and, under a shared ``data_root``, is already
comingled across repos), so it belongs to the default/host repo — "the default
repo keeps its history". Member repos start clean and never claim flat data.

Idempotent: a store is migrated only when the scoped target is absent and the
flat source exists; a copy failure is logged and skipped so startup never
crashes on migration.
"""

from __future__ import annotations

import logging
import shutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from config import HydraFlowConfig

logger = logging.getLogger("hydraflow.data_migration")

# Per-repo insight files under ``memory/`` that move to ``repo_memory_dir``.
# NOTE: deliberately excludes cross-repo knowledge that stays flat
# (``adr_decisions.jsonl``, ``hitl_recommendations.jsonl``, ``items.jsonl``,
# ``verification_records.jsonl``) and out-of-scope per-repo stores deferred to a
# follow-up (``outcomes.jsonl``, ``item_scores.json``, known-pattern /
# troubleshooting files).
_MEMORY_STORES: tuple[str, ...] = (
    "retrospectives.jsonl",
    "filed_patterns.json",
    "retrospective_queue.jsonl",
    "harness_failures.jsonl",
    "harness_suggestions.jsonl",
    "harness_proposed.json",
    "reviews.jsonl",
    "proposed_categories.json",
    "proposal_metadata.json",
)

# Cost/telemetry files under ``metrics/prompt/`` that move to the scoped tree.
_PROMPT_METRIC_STORES: tuple[str, ...] = (
    "inferences.jsonl",
    "pr_stats.json",
)


def _migrate_file(flat: Path, scoped: Path) -> None:
    """Copy ``flat`` → ``scoped`` if the target is absent and the source exists."""
    if flat == scoped or scoped.exists() or not flat.exists():
        return
    try:
        scoped.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(flat, scoped)
    except OSError as exc:
        logger.warning("Failed to migrate %s → %s: %s", flat, scoped, exc)


def _migrate_tree(flat: Path, scoped: Path) -> None:
    """Copy directory tree ``flat`` → ``scoped`` if the target is absent."""
    if flat == scoped or scoped.exists() or not flat.is_dir():
        return
    try:
        shutil.copytree(flat, scoped)
    except OSError as exc:
        logger.warning("Failed to migrate tree %s → %s: %s", flat, scoped, exc)


def migrate_flat_operational_stores(config: HydraFlowConfig) -> None:
    """Relocate legacy flat per-repo stores into the repo-scoped layout.

    Idempotent and host-only — see module docstring. A no-op when there is no
    repo slug to scope under (``repo_data_root == data_root``).
    """
    data_root = config.data_root
    scoped_root = config.repo_data_root
    if scoped_root == data_root:
        return

    flat_memory = data_root / "memory"
    for name in _MEMORY_STORES:
        _migrate_file(flat_memory / name, config.repo_memory_dir / name)

    flat_prompt = data_root / "metrics" / "prompt"
    scoped_prompt = scoped_root / "metrics" / "prompt"
    for name in _PROMPT_METRIC_STORES:
        _migrate_file(flat_prompt / name, scoped_prompt / name)

    _migrate_file(
        data_root / "diagnostics" / "factory_metrics.jsonl",
        config.factory_metrics_path,
    )

    _migrate_tree(data_root / "runs", scoped_root / "runs")
