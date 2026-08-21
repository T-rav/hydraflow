"""HydraFlow server entry point."""

from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import logging
import os
import signal
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from boot_gap_detector import compute_boot_gap_alert, last_event_timestamp
from config import HydraFlowConfig, build_credentials
from events import EventType, HydraFlowEvent
from factory_autostart import maybe_autostart_host
from log import setup_logging
from prompt_gate import most_restrictive_data_class
from runtime_config import (
    DEFAULT_LOG_FILE,
    load_runtime_config,
    valid_stored_overrides,
)
from unpushed_branch_alert import check_and_alert_unpushed_branches

if TYPE_CHECKING:
    from collections.abc import Sequence

    from dashboard import HydraFlowDashboard
    from events import EventBus
    from repo_runtime import RepoRuntimeRegistry
    from repo_store import RepoRegistryStore

logger = logging.getLogger("hydraflow.server")


async def _restore_registered_repos(
    repo_store: RepoRegistryStore, registry: RepoRuntimeRegistry
) -> None:
    """Restore persisted repos from the store into the in-memory registry.

    The repo store persists to disk, but the registry is in-memory — without
    this, added repos are lost on restart and their play buttons return 404.

    Each repo's persisted operator edits (``RepoRecord.overrides``, #10658) are
    read back through :func:`valid_stored_overrides` and merged **under** the
    structural keys (``repo_root`` / ``repo`` / ``repo_data_class``) so an edit
    survives the restart while a stale stored value can never hijack repo
    identity or the CH-6 data-class governance merge. Both ``load_runtime_config``
    calls carry the stored edits — the data-class reload must too, or an
    upgrade path would silently drop the edit.
    """
    for record in repo_store.list():
        if not record.path:
            continue
        if record.slug in registry:
            # Already registered (e.g. the host repo added above) — skip.
            continue
        repo_path = Path(record.path)
        if not repo_path.is_dir():
            logger.warning(
                "Skipping stored repo %s — path %s not found",
                record.slug,
                record.path,
            )
            continue
        try:
            stored = valid_stored_overrides(record.overrides, record.slug)
            repo_cfg = load_runtime_config(
                overrides={
                    **stored,
                    "repo_root": str(repo_path),
                    **({"repo": record.repo} if record.repo else {}),
                }
            )
            # CH-6 (#9734): the registry's data-class declaration rides the
            # per-repo config so prompt_gate enforces it. Merge upward-only —
            # a defaulted record must never downgrade a class the repo's own
            # config file declares (that would be fail-open).
            effective_class = most_restrictive_data_class(
                repo_cfg.repo_data_class, record.data_class
            )
            if repo_cfg.repo_data_class != effective_class:
                repo_cfg = load_runtime_config(
                    overrides={
                        **stored,
                        "repo_root": str(repo_path),
                        **({"repo": record.repo} if record.repo else {}),
                        "repo_data_class": effective_class,
                    }
                )
            await registry.register(repo_cfg)
            logger.info("Restored registered repo %r from store", record.slug)
        except Exception:
            logger.warning("Failed to restore repo %s", record.slug, exc_info=True)


def _detect_submodule_parent(hydraflow_root: Path) -> Path | None:
    """Return the parent repo path if HydraFlow is a git submodule, else None."""
    git_path = hydraflow_root / ".git"
    if not git_path.is_file():
        return None  # .git is a directory — standalone repo, not a submodule
    parent = hydraflow_root.parent
    if (parent / ".git").exists():
        return parent
    return None


async def _detect_remote_slug(repo_path: Path) -> str | None:
    """Detect GitHub slug (owner/repo) from git remote origin URL."""
    try:
        import re  # noqa: PLC0415

        from subprocess_util import run_subprocess  # noqa: PLC0415

        url = await run_subprocess("git", "remote", "get-url", "origin", cwd=repo_path)
        url = url.strip()
        # Parse: https://github.com/owner/repo.git or git@github.com:owner/repo.git
        match = re.search(r"[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
        return match.group(1) if match else None
    except (RuntimeError, OSError):
        return None


async def _check_and_publish_boot_gap(config: HydraFlowConfig, bus: EventBus) -> None:
    """#10009: if events.jsonl's last entry is older than
    ``config.boot_gap_alert_threshold_seconds``, publish one SYSTEM_ALERT so
    the dashboard shows "factory was down ~Xh" instead of a silent gap.

    Extracted as its own small async seam — directly unit-testable with a
    lightweight bus/config — from the surrounding ``_run_with_dashboard``
    boot sequence, which binds real ports and signal handlers and is
    intentionally NOT unit-tested end-to-end (see the ``TestRunDispatch``
    precedent in ``tests/test_server.py``).

    Must be called BEFORE anything else appends a new event (e.g. the
    PHASE_CHANGE publish below, or the dashboard's own startup events) — the
    gap has to reflect genuine downtime, not this boot's own activity.
    """
    boot_at = datetime.now(UTC)
    last_event_at = last_event_timestamp(config.event_log_path)
    alert = compute_boot_gap_alert(
        last_event_at=last_event_at,
        boot_at=boot_at,
        threshold_seconds=config.boot_gap_alert_threshold_seconds,
    )
    if alert is not None:
        logger.warning("Boot-gap detected: %s", alert.get("message", ""))
        await bus.publish(HydraFlowEvent(type=EventType.SYSTEM_ALERT, data=alert))


async def _boot_factory(
    config: HydraFlowConfig,
) -> tuple[HydraFlowDashboard, RepoRuntimeRegistry]:
    """Boot the factory up to (and including) autostart — everything
    ``_run_with_dashboard`` does before it blocks forever on
    ``stop_event.wait()``.

    Deliberately extracted into its own async function — same precedent as
    ``_check_and_publish_boot_gap`` — so the ``maybe_autostart_host`` boot-time
    call site (#11208) is directly unit-testable without booting a real
    dashboard or blocking on a signal handler.
    """
    from dashboard import HydraFlowDashboard  # noqa: PLC0415
    from events import EventBus, EventLog  # noqa: PLC0415
    from models import Phase  # noqa: PLC0415
    from repo_runtime import RepoRuntime, RepoRuntimeRegistry  # noqa: PLC0415
    from repo_store import RepoRecord, RepoRegistryStore  # noqa: PLC0415
    from service_registry import build_state_tracker  # noqa: PLC0415

    event_log = EventLog(config.event_log_path)
    bus = EventBus(event_log=event_log)
    await bus.rotate_log(
        config.event_log_max_size_mb * 1024 * 1024,
        config.event_log_retention_days,
    )
    await bus.load_history_from_disk()
    await _check_and_publish_boot_gap(config, bus)

    state = build_state_tracker(config)

    repo_store = RepoRegistryStore(config.data_root)
    registry = RepoRuntimeRegistry()

    # The host repo is a first-class factory line: register it as a runtime
    # that shares the app-level bus/state (already rotated + history-loaded
    # above) so the dashboard's default (no-repo) views and the host's own
    # start/stop resolve through the registry uniformly — no special-casing.
    host_runtime = RepoRuntime.from_shared(config, bus, state)
    registry.add(host_runtime)

    # Boot-time committed-but-unpushed local branch check (#10011). The host
    # runtime uses from_shared (reusing the already-built bus/state) rather
    # than RepoRuntime.create, so it doesn't get the check for free the way
    # headless mode and restored/added repos do — run it explicitly here.

    try:
        await check_and_alert_unpushed_branches(config, bus)
    except Exception:
        logger.warning("Unpushed-branch boot check failed for host repo", exc_info=True)

    # Restore previously registered repos (and their persisted per-repo config
    # overrides, #10658) into the runtime registry.
    await _restore_registered_repos(repo_store, registry)

    # Auto-register parent repo when running as a git submodule
    hydraflow_root = Path(__file__).resolve().parent.parent
    submodule_parent = _detect_submodule_parent(hydraflow_root)
    if submodule_parent is not None:
        try:
            parent_slug = await _detect_remote_slug(submodule_parent)
            if parent_slug and parent_slug not in registry:
                repo_cfg = load_runtime_config(
                    overrides={
                        "repo_root": str(submodule_parent),
                        "repo": parent_slug,
                    }
                )
                await registry.register(repo_cfg)
                repo_store.upsert(
                    RepoRecord(
                        slug=parent_slug, repo=parent_slug, path=str(submodule_parent)
                    )
                )
                logger.info(
                    "Auto-registered parent repo %s (submodule detected)", parent_slug
                )
        except Exception:
            logger.debug("Submodule auto-registration failed", exc_info=True)

    async def _register_repo(
        repo_path: Path, slug: str | None, data_class: str | None = None
    ) -> tuple[RepoRecord, HydraFlowConfig]:
        from runtime_config import (  # noqa: PLC0415
            load_runtime_config,
            valid_stored_overrides,
        )

        repo_cfg = load_runtime_config(
            overrides={
                "repo_root": str(repo_path),
                **({"repo": slug} if slug else {}),
            }
        )
        # Use the GitHub slug (owner/repo) for the record, not the
        # filesystem-safe repo_slug (owner-repo).
        github_slug = slug or repo_cfg.repo
        # CH-6 (#9734): merge the API declaration, any stored declaration,
        # and the repo's own config-derived class — upward-only, so nothing
        # can downgrade a stricter declaration (fail closed). Reload the
        # config with the effective class so the RUNNING runtime enforces it
        # immediately — a record/config mismatch would be fail-open.
        existing = repo_store.get(github_slug)
        effective_class = most_restrictive_data_class(
            repo_cfg.repo_data_class,
            existing.data_class if existing else None,
            data_class,
        )
        # Re-apply the repo's persisted operator edits (#10658) so re-adding a
        # known repo reproduces its stored config, layered under the structural
        # keys. Reload whenever there are stored overrides or a data-class change.
        stored = (
            valid_stored_overrides(existing.overrides, github_slug) if existing else {}
        )
        if stored or repo_cfg.repo_data_class != effective_class:
            repo_cfg = load_runtime_config(
                overrides={
                    **stored,
                    "repo_root": str(repo_path),
                    **({"repo": slug} if slug else {}),
                    "repo_data_class": effective_class,
                }
            )
        record = repo_store.upsert(
            RepoRecord(
                slug=github_slug,
                repo=github_slug,
                path=str(repo_path),
                data_class=effective_class,
            )
        )
        if record.slug not in registry:
            await registry.register(repo_cfg)
        return record, repo_cfg

    async def _remove_repo(slug: str) -> bool:
        # The UI sends the path-sanitized slug the listing emitted; the
        # registry is keyed by the RAW record slug — resolve first (#9887).
        raw = repo_store.resolve_slug(slug) or slug
        rt = registry.remove(raw)
        if rt is not None:
            await rt.stop()
        return repo_store.remove(raw)

    credentials = build_credentials(config)

    dashboard = HydraFlowDashboard(
        config=config,
        event_bus=bus,
        state=state,
        host_runtime=host_runtime,
        registry=registry,
        repo_store=repo_store,
        register_repo_cb=_register_repo,
        remove_repo_cb=_remove_repo,
        list_repos_cb=repo_store.list,
        default_repo_slug=config.repo_slug,
        credentials=credentials,
    )
    await dashboard.start()

    # Autostart the host orchestrator once the server is healthy — the
    # server-up != factory-running gap (#11208). Fires the exact same path
    # POST /api/control/start does; suppressed by config, an active
    # operator-stopped latch, or an already-running host (see
    # factory_autostart.decide_autostart).
    await maybe_autostart_host(
        config=config, host_runtime=host_runtime, state=state, event_bus=bus
    )

    await bus.publish(
        HydraFlowEvent(
            type=EventType.PHASE_CHANGE,
            data={"phase": Phase.IDLE.value},
        )
    )

    return dashboard, registry


async def _run_with_dashboard(config: HydraFlowConfig) -> None:
    dashboard, registry = await _boot_factory(config)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    try:
        await stop_event.wait()
    finally:
        # The host is a registered runtime now, so stop_all() halts it along
        # with every other factory line.
        await registry.stop_all()
        await dashboard.stop()


async def _run_headless(config: HydraFlowConfig) -> None:
    from repo_runtime import RepoRuntime  # noqa: PLC0415

    runtime = await RepoRuntime.create(config)

    # Strong refs + done-callback for shutdown tasks (#6513) so the GC can't
    # collect the Task before ``runtime.stop()`` completes and exceptions are
    # surfaced instead of silently swallowed by the event loop.
    shutdown_tasks: set[asyncio.Task[None]] = set()

    def _on_shutdown_done(t: asyncio.Task[None]) -> None:
        shutdown_tasks.discard(t)
        try:
            exc = t.exception()
        except asyncio.CancelledError:
            return
        if exc is not None:
            logger.warning("runtime.stop() task failed", exc_info=exc)

    def _schedule_stop() -> None:
        task = asyncio.create_task(runtime.stop())
        shutdown_tasks.add(task)
        task.add_done_callback(_on_shutdown_done)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _schedule_stop)

    await runtime.run()


async def _run_preflight(config: HydraFlowConfig) -> bool:
    """Run preflight checks; return True if startup should proceed."""
    from preflight import log_preflight_results, run_preflight_checks  # noqa: PLC0415

    if config.skip_preflight:
        logger.info("Preflight checks skipped (skip_preflight=True)")
        return True
    results = await run_preflight_checks(config)
    healthy = log_preflight_results(results)
    if not healthy:
        logger.error("Preflight checks failed — aborting startup")
    return healthy


async def _run(config: HydraFlowConfig) -> None:
    # NOTE: Tests patch _run_with_dashboard / _run_headless (private names)
    # because these are heavyweight server-starting functions that bind ports
    # and block forever.  Extracting them as injectable dependencies would be
    # over-engineering for a two-branch dispatch function.
    #
    # One-time, host-only migration of legacy flat per-repo stores into the
    # repo-scoped layout (ADR-0021 D2). Runs once with the host config before
    # any runtime/member is built, so member repos never claim the host's
    # legacy flat data. Idempotent — a no-op once migrated.
    from data_migration import migrate_flat_operational_stores  # noqa: PLC0415

    migrate_flat_operational_stores(config)
    if not await _run_preflight(config):
        return
    if config.dashboard_enabled:
        await _run_with_dashboard(config)
    else:
        await _run_headless(config)


def package_version() -> str:
    """Version of the running HydraFlow: installed metadata, else the checkout.

    A wheel / editable install answers through ``importlib.metadata``. A bare
    checkout run with ``PYTHONPATH=src`` (``make run``, the agent image's
    ``--no-install-project`` venv) has no metadata, so fall back to the
    ``[project] version`` in the checkout's ``pyproject.toml``.
    """
    try:
        return importlib.metadata.version("hydraflow")
    except importlib.metadata.PackageNotFoundError:
        pass
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    try:
        return str(tomllib.loads(pyproject.read_text("utf-8"))["project"]["version"])
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return "unknown"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """CLI surface of the ``hydraflow`` console script (#11580).

    Configuration is environment-driven (``.env`` / ``HYDRAFLOW_*``), so the
    only options are ``--help`` and ``--version`` — both answer without
    touching config, logging or the event loop, which is what lets an
    installed wheel be smoke-tested in a clean venv.
    """
    parser = argparse.ArgumentParser(
        prog="hydraflow",
        description=(
            "Start the HydraFlow server. Configuration is read from the "
            "environment and .env (HYDRAFLOW_* keys; see README.md)."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {package_version()}",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    parse_args(argv)
    from dotenv import load_dotenv  # noqa: PLC0415

    load_dotenv()

    verbose = os.environ.get("HYDRAFLOW_VERBOSE_LOGS", "").strip() not in {
        "",
        "0",
        "false",
        "False",
    }
    log_path = os.environ.get("HYDRAFLOW_LOG_FILE", str(DEFAULT_LOG_FILE))
    level = logging.DEBUG if verbose else logging.INFO
    setup_logging(level=level, json_output=not verbose, log_file=log_path)

    config = load_runtime_config()

    logging.getLogger("hydraflow.server").info(
        "Starting HydraFlow server (dashboard=%s)", config.dashboard_enabled
    )
    asyncio.run(_run(config))


if __name__ == "__main__":
    main()
