"""Shared fixtures and factories for HydraFlow tests."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ADR-0052: Sandbox-tier scenarios run only inside the docker-compose stack
# (`docker-compose.sandbox.yml`). They use their own pytest.ini with a
# hard-coded `--confcutdir=/work/tests/sandbox_scenarios` that resolves only
# inside the playwright container. Skipping them at collection time here keeps
# host-side `pytest tests/` and `make quality` green; CI runs them via the
# dedicated `sandbox` job (`scripts/sandbox_scenario.py`).
collect_ignore_glob = ["sandbox_scenarios/*"]

# The test suite and MockWorld scenarios run with fixture data — issue #42,
# PR #101, "boom" failure sentinels, AsyncMock collaborators. None of it must
# ever reach the real Sentry project. A real SENTRY_DSN in the ambient env
# (e.g. loaded from .env on a developer/CI box) would otherwise let any test
# that spins up the server or logs an error ship that fixture noise to
# production Sentry. Neutralise it at import time — before collection — so the
# guard holds regardless of which test triggers init. `_init_sentry` also
# honours HYDRAFLOW_SENTRY_DISABLED; the Sentry integration tests opt back in
# explicitly via `force=True` against a mock SDK. SENTRY_AUTH_TOKEN is popped
# alongside SENTRY_DSN for the same reason — it's a credential fallback read
# directly by `build_credentials()`, outside any `_ENV_*_OVERRIDES` table, so
# `declared_env_keys()` below can't cover it (#10876).
os.environ["HYDRAFLOW_SENTRY_DISABLED"] = "1"
os.environ.pop("SENTRY_DSN", None)
os.environ.pop("SENTRY_AUTH_TOKEN", None)


# #10094: committed sandbox seeds under tests/sandbox_scenarios/seeds/ must
# never be mutated by the test suite (write_seed() materializing a
# MockWorldSeed round-trip back onto its own source path adds schema
# defaults like "comments": {} that then leak into unrelated commits).
# tests/regressions/regression_issue_10094.py's `test_seed_dir_is_git_clean`
# proves the dir was clean at ONE point in collection order; under
# `-n auto --dist loadscope` a later test on a DIFFERENT xdist worker could
# still dirty it afterward and go uncaught there. Snapshotting mtimes at
# import time (before this process — controller or worker — runs its first
# test) and re-checking after EVERY test's teardown closes that gap and, like
# the MagicMock guard below, pins the exact offending test by name instead of
# surfacing as an unexplained ` M` diff days later.
_SANDBOX_SEEDS_DIR = Path(__file__).resolve().parent / "sandbox_scenarios" / "seeds"


def _sandbox_seed_mtimes(seeds_dir: Path = _SANDBOX_SEEDS_DIR) -> dict[str, int]:
    """Snapshot ``{name: st_mtime_ns}`` for every ``*.json`` seed in *seeds_dir*.

    #11552: ``glob()`` and ``stat()`` are two syscalls, and under
    ``-n auto --forked`` another worker can unlink a TRANSIENT seed between
    them (``regression_issue_10094.py`` materializes and removes the seedless
    ``s75_worker_stall_escalation.json`` + ``scenario.json`` in this very dir).
    A path that vanished after discovery is not a committed seed, so it cannot
    be a #10094 violation — skip ONLY that path. Any other ``stat()`` failure
    still propagates.
    """
    if not seeds_dir.is_dir():
        return {}
    mtimes: dict[str, int] = {}
    for path in seeds_dir.glob("*.json"):
        try:
            mtimes[path.name] = path.stat().st_mtime_ns
        except FileNotFoundError:
            continue
    return mtimes


# #10094 + #11016: snapshot per TEST (setup -> teardown), not once at import.
# The old import-time module-global baseline assumed one long-lived process per
# xdist worker; under `--forked` (#11004) each test forks carrying that stale
# baseline and its per-fork "absorb" never propagates, so a single harmless
# re-serialization (identical bytes, new mtime — git stays clean) made EVERY
# later forked test blame itself. Scope the check to each test's OWN window and
# only fail on real CONTENT drift (what #10094 cares about — a bare mtime bump
# git ignores is not a violation).
_SEED_MTIMES_KEY = pytest.StashKey[dict[str, int]]()


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Snapshot committed-seed mtimes at THIS test's start (see the teardown)."""
    item.stash[_SEED_MTIMES_KEY] = _sandbox_seed_mtimes()


def _content_dirty_seeds(
    names: list[str], *, seeds_dir: Path = _SANDBOX_SEEDS_DIR
) -> list[str]:
    """Of *names*, those whose CONTENT actually differs from git (index/HEAD).

    A re-serialization that writes identical bytes bumps mtime but leaves git
    clean — harmless, NOT a #10094 violation; only real content drift is. On any
    git failure return ``[]`` (fail-open): the dedicated
    ``regression_issue_10094.py::test_seed_dir_is_git_clean`` is the authoritative
    content backstop, so this teardown hook is the by-name locator, not the gate.
    """
    if not names:
        return []
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain", "--", str(seeds_dir)],
            cwd=seeds_dir.parent,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    dirty = {
        line[3:].strip().rsplit("/", 1)[-1] for line in out.splitlines() if line.strip()
    }
    return sorted(n for n in names if n in dirty)


def _mutated_committed_seeds(
    before: dict[str, int], *, seeds_dir: Path = _SANDBOX_SEEDS_DIR
) -> list[str]:
    """Committed seeds whose mtime moved since *before* AND whose content is dirty.

    Only a real CONTENT change is a #10094 violation; a bare mtime bump from
    re-serializing identical bytes leaves git clean and is harmless (and under
    --forked was blaming innocents). Confirm content drift via git first.
    """
    current = _sandbox_seed_mtimes(seeds_dir)
    touched = sorted(
        name for name, mtime in current.items() if before.get(name) != mtime
    )
    return _content_dirty_seeds(touched, seeds_dir=seeds_dir)


def pytest_runtest_teardown(item: pytest.Item, nextitem: pytest.Item | None) -> None:  # noqa: ARG001 — nextitem required by pytest hook signature
    """Fail any test that leaves a ``MagicMock/`` directory in the repo root,

    or that mutates a committed sandbox seed (#10094).

    Caused by passing a bare ``MagicMock()`` where production code expects a
    ``Path`` / config and calls ``.mkdir()`` on the result — the str() of the
    mock becomes the first path segment (``MagicMock``), subsequent
    attribute-access calls become further segments (``mock.data_path()``),
    and the real filesystem picks them up. The dirs then get swept into
    commits accidentally.

    Fail fast so the offending test is immediately obvious. The remediation
    is usually ``MagicMock(spec=HydraFlowConfig)`` or a real
    ``tmp_path``-backed config (see ``ConfigFactory``).
    """
    root = Path(item.config.rootpath)
    polluted = root / "MagicMock"
    if polluted.exists():
        shutil.rmtree(polluted, ignore_errors=True)
        pytest.fail(
            f"Mock-path pollution: test {item.nodeid} left {polluted} on disk. "
            "A MagicMock was used where a Path/config was expected. "
            "Use `MagicMock(spec=HydraFlowConfig)` or a real tmp_path-backed config."
        )

    before = item.stash.get(_SEED_MTIMES_KEY, None)
    if before is None:
        return
    mutated_seeds = _mutated_committed_seeds(before)
    if mutated_seeds:
        pytest.fail(
            f"Sandbox-seed tree-clean violation: test {item.nodeid} mutated "
            f"committed seed(s) {mutated_seeds} in "
            "tests/sandbox_scenarios/seeds/. Seeds are golden generated "
            "artifacts — a test/fixture must never re-serialize a materialized "
            "MockWorldSeed back to the source path with changed content; "
            "redirect the write to tmp_path instead (#10094)."
        )


@pytest.hookimpl(hookwrapper=True, tryfirst=True, specname="pytest_runtest_teardown")
def pytest_cleanup_config_factory_temp_roots():
    """Release this pytest process's implicit config roots after fixture teardown."""

    try:
        yield
    finally:
        # pytest-forked terminates each child with os._exit(), bypassing atexit.
        # The runtest teardown still executes in that child, so release only the
        # roots owned by its PID here; the registered atexit cleanup remains the
        # fallback for ordinary interpreter shutdown outside pytest.
        from tests.helpers import _cleanup_owned_config_factory_temp_roots

        _cleanup_owned_config_factory_temp_roots()


# --- Test-duration ratchet (CI-speedup Tier 4a) -----------------------------
# Prevent the suite from silently accumulating slow / hung tests. A test whose
# CALL phase exceeds a deliberately generous budget FAILS with a clear message,
# unless it is in the explicit shrink-only grandfather set below. This catches
# new pathologically-slow or hung tests (a real one recently hung ~300s under
# parallel execution) without flaking on ordinary machine variance.
#
# Follow-up (deliberately NOT done here): move genuinely-slow tests behind a
# `@pytest.mark.slow` marker and run them in a dedicated nightly "slow" lane
# instead of grandfathering them. That is a separate change; this ratchet only
# guards the fast lane against regressions.
_SLOW_TEST_BUDGET_S = 60.0
# Tests legitimately over budget today (measured under parallel CPU contention,
# so these are upper bounds). SHRINK-ONLY: optimize a test and remove it here;
# never add a new one without justification. Optimizing these is tracked as a
# follow-up.
_SLOW_TEST_GRANDFATHER = frozenset(
    {
        "tests/test_audit_prompts.py::test_main_emits_report_to_expected_path",
        "tests/test_audit_prompts.py::test_canary_cross_check_passes_when_every_trace_builder_registered",
        "tests/test_audit_prompts.py::test_canary_cross_check_flags_drift_over_threshold",
        "tests/test_orchestrator_integration.py::test_credit_pause_publishes_alerts_and_restores_loops",
        # s34 is a full diagram-loop no-op sandbox scenario that legitimately
        # runs right at the ~60s budget (60.1–60.7s), so it flakes the ratchet
        # every other run and blocks unrelated PRs (#10772, #10811, and all
        # session PRs). Exempt it; the scenario body is already a fixed no-op.
        "tests/scenarios/test_sandbox_parity.py::test_sandbox_scenario_runs_in_process[s34_diagram_loop_no_changes]",
    }
)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]):  # noqa: ARG001 — call required by pytest hook signature
    """Fail any test whose CALL phase exceeds the slow-test budget.

    Grandfathered node ids are exempt (shrink-only — see
    ``_SLOW_TEST_GRANDFATHER``). The budget is intentionally generous so normal
    machine variance never trips it; only pathologically-slow or hung tests do.
    """
    outcome = yield
    report = outcome.get_result()
    if (
        report.when == "call"
        and report.passed
        and report.duration > _SLOW_TEST_BUDGET_S
    ):
        nodeid = item.nodeid
        if nodeid not in _SLOW_TEST_GRANDFATHER:
            report.outcome = "failed"
            report.longrepr = (
                f"Duration ratchet: {nodeid} took {report.duration:.1f}s "
                f"(> {_SLOW_TEST_BUDGET_S:.0f}s budget). Optimize it, or if it is "
                f"unavoidably slow add it to _SLOW_TEST_GRANDFATHER in "
                f"tests/conftest.py (shrink-only)."
            )


# Ensure source modules are importable from src/ layout.
_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))
sys.path.insert(0, str(_REPO_ROOT))

import subprocess_util  # noqa: E402
from config import (  # noqa: E402
    CREDENTIAL_ENV_KEYS,
    clear_dotenv_inert_roots,
    declared_env_keys,
    mark_default_repo_dotenv_inert,
)
from tests.helpers import ConfigFactory  # noqa: E402

if TYPE_CHECKING:
    from ci_scaffold import CIScaffoldResult
    from config import HydraFlowConfig
    from events import HydraFlowEvent
    from models import (
        AnalysisResult,
        GitHubIssue,
        GitHubIssueState,
        HITLResult,
        NewIssueSpec,
        PlanResult,
        PRInfo,
        ReviewResult,
        ReviewVerdict,
        WorkerResult,
    )
    from orchestrator import HydraFlowOrchestrator
    from state import StateTracker
    from test_scaffold import TestScaffoldResult


# --- Session-scoped environment setup ---
#
# NOTE ON GLOBAL STATE MUTATION:
# The fixtures below intentionally mutate global state (os.environ and
# module-level private variables) to create a hermetic test environment.
#
# - ``setup_test_environment`` removes every env var ``config.declared_env_keys()``
#   covers (every key any ``_ENV_*_OVERRIDES`` table reads, prefixed or not —
#   e.g. ``SENTRY_ORG``, ``HF_ENV``) plus the ``HYDRAFLOW_*``/``HYDRA_*`` prefix
#   sweep (belt-and-braces: some prefixed keys are read directly, outside the
#   tables) and a fixed GIT_*/credential-fallback list, so tests don't
#   accidentally pick up the host's configuration (#10876).  A ``finally``
#   block restores original values after all tests in the session complete.
#   An abnormal process termination (SIGKILL, segfault) will kill the pytest
#   process before the ``finally`` runs, but since the environment is
#   process-local, it cannot affect any other process — this is an acceptable
#   trade-off.
#
# - ``_reset_gh_semaphore`` clears module-level private state in
#   subprocess_util to prevent cross-test leakage of semaphore/rate-limit
#   state.  This couples tests to internal implementation details; if those
#   internals are renamed, this fixture must be updated accordingly.


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Set minimal env vars and isolate tests from host configuration.

    Removes every env var ``config.declared_env_keys()`` covers — every key
    any ``_ENV_*_OVERRIDES`` table declares, prefixed or not (e.g.
    ``SENTRY_ORG``, ``HF_ENV``) — union the ``HYDRAFLOW_*``/``HYDRA_*``
    prefix rule (belt-and-braces: some prefixed keys are read directly,
    outside the tables) union a fixed ``GIT_*``/credential-fallback list,
    from ``os.environ`` for the duration of the test session, then restores
    them in a ``finally`` block. This is intentional global state mutation
    required for test isolation — see module-level note above. Without this,
    a non-``HYDRAFLOW_``/``HYDRA_``-prefixed override exported on the host or
    CI runner leaks into every ``HydraFlowConfig`` built during the session
    (#10876).

    GIT identity vars (``GIT_AUTHOR_*`` / ``GIT_COMMITTER_*``) are scrubbed
    AND replaced with deterministic test values. CI runners have no global
    git config; without a default identity, any test that exercises the
    "use ambient identity" fallback (e.g. ``open_automated_pr_async`` with
    empty author overrides) fails with ``Author identity unknown``. Tests
    that explicitly want to verify the no-identity error path can call
    ``monkeypatch.delenv("GIT_AUTHOR_NAME", raising=False)`` (and the
    other three keys) at the top of the test. See feedback memory
    ``feedback_ci_no_global_git_config.md`` (PR #8354) and
    ``docs/superpowers/specs/2026-05-07-tier2-enforcement-batch-design.md`` §5.

    ``GITHUB_TOKEN`` is scrubbed too: it's the lowest-priority fallback in
    ``build_credentials()``'s ``gh_token`` chain, behind the ``GH_TOKEN``
    seeded below — but a test that deletes ``GH_TOKEN`` to probe that
    fallback path must not fall through to the host's real token.

    ``GITHUB_OUTPUT`` is scrubbed as well (#11562): GitHub Actions always sets
    it, and the CLI scripts under ``scripts/`` default ``--github-output`` /
    ``--out`` to it. A test that calls such a ``main()`` in-process without the
    flag would otherwise write the verdict into the runner's REAL step-output
    file instead of stdout — green on every laptop, red only on CI (PR #11560),
    and polluting the job's outputs. Tests that want the variable set pass
    ``env=`` to a subprocess explicitly. ``tests/architecture/
    test_github_output_hermetic.py`` pins this scrub.
    """
    # Imported lazily (not at module scope) to keep runner_utils' heavier
    # import chain (execution/subprocess_util/process_group/...) out of
    # conftest's own top-level imports.
    from runner_utils import provider_api_key_envs

    test_env = {
        "HOME": "/tmp/hydraflow-test",
        "GH_TOKEN": "test-token",
        "GIT_AUTHOR_NAME": "HydraFlow Test",
        "GIT_AUTHOR_EMAIL": "test@hydraflow.local",
        "GIT_COMMITTER_NAME": "HydraFlow Test",
        "GIT_COMMITTER_EMAIL": "test@hydraflow.local",
        # Re-seed the kill switch set at conftest import time (module scope,
        # above): the HYDRAFLOW_* prefix sweep below would otherwise pop it
        # and never restore it for the session (#10876).
        "HYDRAFLOW_SENTRY_DISABLED": "1",
    }
    scrub_keys = (
        {key for key in os.environ if key.startswith(("HYDRAFLOW_", "HYDRA_"))}
        | declared_env_keys()
        # The credential surface build_credentials reads (#10885): scrubbed from
        # the exported registry instead of hand-listing GITHUB_TOKEN. GH_TOKEN is
        # re-seeded to "test-token" via test_env below.
        | CREDENTIAL_ENV_KEYS
        # Bare (non-HYDRAFLOW_-prefixed) provider API key envs — ZAI_API_KEY,
        # ZAI_CODING_PLAN_KEY, OPENROUTER_API_KEY, MOONSHOT_API_KEY, ... —
        # carry no prefix and live in neither declared_env_keys() nor
        # CREDENTIAL_ENV_KEYS, so an ambient developer/CI shell export leaks
        # into every test session and defeats "*_without_zai_key"-style
        # preconditions unless swept up here too.
        | provider_api_key_envs()
        | {
            "GIT_DIR",
            "GIT_WORK_TREE",
            "GIT_AUTHOR_NAME",
            "GIT_AUTHOR_EMAIL",
            "GIT_COMMITTER_NAME",
            "GIT_COMMITTER_EMAIL",
            # Actions step-output file; see the docstring (#11562).
            "GITHUB_OUTPUT",
        }
    )
    saved_env = {key: os.environ.pop(key) for key in scrub_keys if key in os.environ}
    # #10902: even with os.environ scrubbed, a default-constructed HydraFlowConfig()
    # resolves repo_root to the real checkout and _dotenv_lookup would read the
    # operator's real .env. Mark that root inert for the session.
    mark_default_repo_dotenv_inert()
    try:
        with patch.dict(os.environ, test_env, clear=False):
            yield
    finally:
        os.environ.update(saved_env)
        clear_dotenv_inert_roots()


@pytest.fixture(autouse=True)
def _reset_gh_semaphore():
    """Reset the global gh semaphore, rate-limit, and circuit-breaker state.

    This directly mutates module-level private state in ``subprocess_util``
    (``_gh_semaphore`` and ``_rate_limit_until``) to prevent cross-test
    leakage.  See module-level note above regarding the coupling trade-off.

    The circuit breaker is cleared through its public ``reset_gh_circuit_breaker``
    entrypoint: without it, a test that tripped the breaker OPEN left it OPEN for
    every later test on the same xdist worker, which then failed fast on
    unrelated gh/git calls (#10907).
    """
    subprocess_util._gh_semaphore = None
    subprocess_util._rate_limit_until = None
    subprocess_util.reset_gh_circuit_breaker()
    yield
    subprocess_util._gh_semaphore = None
    subprocess_util._rate_limit_until = None
    subprocess_util.reset_gh_circuit_breaker()


@pytest.fixture(autouse=True)
def _reset_prompt_telemetry_health_state():
    """Clear the in-process prompt-ledger health latch between tests."""
    import prompt_telemetry

    with prompt_telemetry._HEALTH_LOCK:
        prompt_telemetry._HEALTH_STATE.clear()
    yield
    with prompt_telemetry._HEALTH_LOCK:
        prompt_telemetry._HEALTH_STATE.clear()


@pytest.fixture(autouse=True)
def _hermetic_credentials(monkeypatch):
    """Strip live provider credentials from every test's environment (#11302).

    A live checkout's shell (or a sourced .env) carries the z.ai key pair and
    the ANTHROPIC redirect pair; tests asserting 'no key configured' behavior
    silently pass/fail depending on the HOST's billing setup — 15+ tests broke
    under make quality on machines with ZAI_CODING_PLAN_KEY set (#11302,
    #11317, #11368 class). Tests that need a credential set it explicitly via
    monkeypatch.setenv, which layers on top of this deletion.
    """
    for key in (
        "ZAI_API_KEY",
        "ZAI_CODING_PLAN_KEY",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_AUTH_TOKEN",
    ):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def _reset_credit_failover():
    """Clear the credit-failover module singleton between tests (#10844).

    ``credit_failover`` holds process-wide runtime state (whether work spawns are
    rerouted to GLM). A test that engages failover must not leak that into a later
    test on the same xdist worker, which would silently reroute its spawns. Cleared
    through the public ``reset_for_tests`` entrypoint (mirrors the gh circuit
    breaker reset above; #10889 module-state reset-coverage pattern).
    """
    import credit_failover

    credit_failover.reset_for_tests()
    yield
    credit_failover.reset_for_tests()


@pytest.fixture(autouse=True)
def _restore_phase_utils_memory_seams():
    """Snapshot + restore the ``phase_utils`` memory-suggestion seams per test.

    Many modules patch ``phase_utils.file_memory_suggestion`` /
    ``safe_file_memory_suggestion`` (review/implement/HITL phase hooks,
    review-phase-metrics, phase-utils' own suite). If a patch escapes its test —
    which xdist's cross-module worker scheduling can trigger — the module
    attribute is left pointing at a stale ``AsyncMock``, so a LATER test's own
    ``with patch(...)`` never rebinds the value the code under test resolves, and
    that test's mock is "awaited 0 times". Snapshot + restore contains the leak
    regardless of which test caused it (mirrors ``_restore_auto_pr_seams`` in
    tests/scenarios/conftest.py). Fixes the whole memory-suggestion category
    under -n auto (#10119 and the phase_utils flake).
    """
    import phase_utils

    saved = (
        phase_utils.file_memory_suggestion,
        phase_utils.safe_file_memory_suggestion,
    )
    try:
        yield
    finally:
        (
            phase_utils.file_memory_suggestion,
            phase_utils.safe_file_memory_suggestion,
        ) = saved


@pytest.fixture(autouse=True)
def _disable_hitl_summary_autowarm(config) -> None:
    """Keep route tests deterministic unless a test explicitly opts in."""
    config.transcript_summarization_enabled = False


# --- Config Fixtures ---


@pytest.fixture
def config(tmp_path: Path) -> HydraFlowConfig:
    return ConfigFactory.create(
        repo_root=tmp_path / "repo",
        workspace_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )


@pytest.fixture
def dry_config(tmp_path: Path) -> HydraFlowConfig:
    return ConfigFactory.create(
        dry_run=True,
        repo_root=tmp_path / "repo",
        workspace_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )


# --- Issue Factory ---


class IssueFactory:
    """Factory for GitHubIssue instances."""

    @staticmethod
    def create(
        *,
        number: int = 42,
        title: str = "Fix the frobnicator",
        body: str = "The frobnicator is broken. Please fix it.",
        labels: list[str] | None = None,
        comments: list[str] | None = None,
        url: str | None = None,
        author: str | None = None,
        state: GitHubIssueState | None = None,
        milestone_number: int | None = None,
        created_at: str | None = None,
    ):
        from models import GitHubIssue  # noqa: F811

        kwargs: dict[str, Any] = {
            "number": number,
            "title": title,
            "body": body,
            "labels": labels if labels is not None else ["ready"],
            "comments": comments if comments is not None else [],
            "url": url
            if url is not None
            else f"https://github.com/test-org/test-repo/issues/{number}",
        }
        if author is not None:
            kwargs["author"] = author
        if state is not None:
            kwargs["state"] = state
        if milestone_number is not None:
            kwargs["milestone_number"] = milestone_number
        if created_at is not None:
            kwargs["created_at"] = created_at
        return GitHubIssue(**kwargs)


@pytest.fixture
def issue() -> GitHubIssue:
    return IssueFactory.create()


# --- Task Factory ---


class TaskFactory:
    """Factory for Task instances."""

    @staticmethod
    def create(
        *,
        id: int = 42,
        title: str = "Fix the frobnicator",
        body: str = "The frobnicator is broken. Please fix it.",
        tags: list[str] | None = None,
        comments: list[str] | None = None,
        source_url: str | None = None,
        links: list[Any] | None = None,
        complexity_score: int = 0,
        created_at: str = "",
        metadata: dict[str, Any] | None = None,
        parent_epic: int | None = None,
    ):
        from models import Task

        return Task(
            id=id,
            title=title,
            body=body,
            tags=tags if tags is not None else ["ready"],
            comments=comments if comments is not None else [],
            source_url=source_url
            if source_url is not None
            else f"https://github.com/test-org/test-repo/issues/{id}",
            links=links if links is not None else [],
            complexity_score=complexity_score,
            created_at=created_at,
            metadata=metadata if metadata is not None else {},
            parent_epic=parent_epic,
        )


# --- Worker Result Factory ---
#
# WorkerResultFactory, PlanResultFactory, PRInfoFactory, ReviewResultFactory,
# and TriageResultFactory now live in src/mockworld/fakes/_factories.py
# (re-exported below for back-compat) so that the Fakes (FakeGitHub, FakeLLM)
# can import them without a ``src→tests`` dependency. PR B's docker container
# does not COPY tests/, so any ``from tests.conftest`` import in src/ would
# fail at module load.
# noqa: F401 — these names are re-exported for back-compat. Many tests
# import directly via ``from tests.conftest import PRInfoFactory`` etc.;
# removing the names here would break them. The ``E402`` noqa is because
# this import follows session-scoped fixture definitions, which is
# intentional in this file.
from mockworld.fakes._factories import (  # noqa: E402, F401
    PlanResultFactory,
    PRInfoFactory,
    ReviewResultFactory,
    TriageResultFactory,
    WorkerResultFactory,
)


class WorkerResultBuilder:
    """Fluent builder for WorkerResult instances."""

    def __init__(self) -> None:
        self._kwargs: dict[str, Any] = {}
        self._use_model_defaults: bool = False

    def with_model_defaults(self) -> WorkerResultBuilder:
        """Use Pydantic model defaults instead of factory hardcoded values."""
        self._use_model_defaults = True
        return self

    def with_issue_number(self, value: int) -> WorkerResultBuilder:
        self._kwargs["issue_number"] = value
        return self

    def with_branch(self, value: str) -> WorkerResultBuilder:
        self._kwargs["branch"] = value
        return self

    def with_success(self, value: bool) -> WorkerResultBuilder:
        self._kwargs["success"] = value
        return self

    def with_transcript(self, value: str) -> WorkerResultBuilder:
        self._kwargs["transcript"] = value
        return self

    def with_commits(self, value: int) -> WorkerResultBuilder:
        self._kwargs["commits"] = value
        return self

    def with_workspace_path(self, value: str) -> WorkerResultBuilder:
        self._kwargs["workspace_path"] = value
        return self

    def with_error(self, value: str) -> WorkerResultBuilder:
        self._kwargs["error"] = value
        return self

    def with_duration_seconds(self, value: float) -> WorkerResultBuilder:
        self._kwargs["duration_seconds"] = value
        return self

    def with_pre_quality_review_attempts(self, value: int) -> WorkerResultBuilder:
        self._kwargs["pre_quality_review_attempts"] = value
        return self

    def with_quality_fix_attempts(self, value: int) -> WorkerResultBuilder:
        self._kwargs["quality_fix_attempts"] = value
        return self

    def with_pr_info(self, value: PRInfo) -> WorkerResultBuilder:
        self._kwargs["pr_info"] = value
        return self

    def build(self) -> WorkerResult:
        """Build the WorkerResult using the factory."""
        return WorkerResultFactory.create(
            use_defaults=self._use_model_defaults, **self._kwargs
        )


# --- Plan Result Factory ---
# (PlanResultFactory now lives in src/mockworld/fakes/_factories.py;
# the import above re-exports it under this module's namespace.)


class PlanResultBuilder:
    """Fluent builder for PlanResult instances."""

    def __init__(self) -> None:
        self._kwargs: dict[str, Any] = {}
        self._use_model_defaults: bool = False

    def with_model_defaults(self) -> PlanResultBuilder:
        """Use Pydantic model defaults instead of factory hardcoded values."""
        self._use_model_defaults = True
        return self

    def with_issue_number(self, value: int) -> PlanResultBuilder:
        self._kwargs["issue_number"] = value
        return self

    def with_success(self, value: bool) -> PlanResultBuilder:
        self._kwargs["success"] = value
        return self

    def with_plan(self, value: str) -> PlanResultBuilder:
        self._kwargs["plan"] = value
        return self

    def with_summary(self, value: str) -> PlanResultBuilder:
        self._kwargs["summary"] = value
        return self

    def with_error(self, value: str) -> PlanResultBuilder:
        self._kwargs["error"] = value
        return self

    def with_transcript(self, value: str) -> PlanResultBuilder:
        self._kwargs["transcript"] = value
        return self

    def with_duration_seconds(self, value: float) -> PlanResultBuilder:
        self._kwargs["duration_seconds"] = value
        return self

    def with_new_issues(self, value: list[NewIssueSpec]) -> PlanResultBuilder:
        self._kwargs["new_issues"] = value
        return self

    def with_validation_errors(self, value: list[str]) -> PlanResultBuilder:
        self._kwargs["validation_errors"] = value
        return self

    def with_retry_attempted(self, value: bool) -> PlanResultBuilder:
        self._kwargs["retry_attempted"] = value
        return self

    def with_already_satisfied(self, value: bool) -> PlanResultBuilder:
        self._kwargs["already_satisfied"] = value
        return self

    def with_actionability_score(self, value: int) -> PlanResultBuilder:
        self._kwargs["actionability_score"] = value
        return self

    def with_actionability_rank(self, value: str) -> PlanResultBuilder:
        self._kwargs["actionability_rank"] = value
        return self

    def with_epic_number(self, value: int) -> PlanResultBuilder:
        self._kwargs["epic_number"] = value
        return self

    def build(self) -> PlanResult:
        """Build the PlanResult using the factory."""
        return PlanResultFactory.create(
            use_defaults=self._use_model_defaults, **self._kwargs
        )


# --- PR Info Factory ---
# (PRInfoFactory now lives in src/mockworld/fakes/_factories.py;
# the import above re-exports it under this module's namespace.)


# --- Review Result Factory ---
# (ReviewResultFactory now lives in src/mockworld/fakes/_factories.py;
# the import above re-exports it under this module's namespace.)


class ReviewResultBuilder:
    """Fluent builder for ReviewResult instances."""

    def __init__(self) -> None:
        self._kwargs: dict[str, Any] = {}
        self._use_model_defaults: bool = False

    def with_model_defaults(self) -> ReviewResultBuilder:
        """Use Pydantic model defaults instead of factory hardcoded values."""
        self._use_model_defaults = True
        return self

    def with_pr_number(self, value: int) -> ReviewResultBuilder:
        self._kwargs["pr_number"] = value
        return self

    def with_issue_number(self, value: int) -> ReviewResultBuilder:
        self._kwargs["issue_number"] = value
        return self

    def with_verdict(self, value: ReviewVerdict) -> ReviewResultBuilder:
        self._kwargs["verdict"] = value
        return self

    def with_success(self, value: bool) -> ReviewResultBuilder:
        self._kwargs["success"] = value
        return self

    def with_error(self, value: str) -> ReviewResultBuilder:
        self._kwargs["error"] = value
        return self

    def with_summary(self, value: str) -> ReviewResultBuilder:
        self._kwargs["summary"] = value
        return self

    def with_fixes_made(self, value: bool) -> ReviewResultBuilder:
        self._kwargs["fixes_made"] = value
        return self

    def with_commit_stat(self, value: str) -> ReviewResultBuilder:
        self._kwargs["commit_stat"] = value
        return self

    def with_transcript(self, value: str) -> ReviewResultBuilder:
        self._kwargs["transcript"] = value
        return self

    def with_merged(self, value: bool) -> ReviewResultBuilder:
        self._kwargs["merged"] = value
        return self

    def with_duration_seconds(self, value: float) -> ReviewResultBuilder:
        self._kwargs["duration_seconds"] = value
        return self

    def with_ci_passed(self, value: bool) -> ReviewResultBuilder:
        self._kwargs["ci_passed"] = value
        return self

    def with_ci_fix_attempts(self, value: int) -> ReviewResultBuilder:
        self._kwargs["ci_fix_attempts"] = value
        return self

    def with_visual_passed(self, value: bool) -> ReviewResultBuilder:
        self._kwargs["visual_passed"] = value
        return self

    def with_files_changed(self, value: list[str]) -> ReviewResultBuilder:
        self._kwargs["files_changed"] = value
        return self

    def build(self) -> ReviewResult:
        """Build the ReviewResult using the factory."""
        return ReviewResultFactory.create(
            use_defaults=self._use_model_defaults, **self._kwargs
        )


# --- HITL Result Factory ---


class HITLResultFactory:
    """Factory for HITLResult instances."""

    @staticmethod
    def create(
        *,
        issue_number: int = 42,
        success: bool = True,
        error: str | None = None,
        transcript: str = "",
        duration_seconds: float = 0.0,
    ) -> HITLResult:
        from models import HITLResult as HR

        return HR(
            issue_number=issue_number,
            success=success,
            error=error,
            transcript=transcript,
            duration_seconds=duration_seconds,
        )


# --- Event Factory ---


class EventFactory:
    """Factory for HydraFlowEvent instances."""

    @staticmethod
    def create(
        *,
        type: Any = None,
        timestamp: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> HydraFlowEvent:
        from events import EventType as ET
        from events import HydraFlowEvent as HE

        return HE(
            type=type if type is not None else ET.PHASE_CHANGE,
            timestamp=timestamp if timestamp is not None else "",
            data=data if data is not None else {},
        )


# --- Triage Result Factory ---
# (TriageResultFactory now lives in src/mockworld/fakes/_factories.py;
# the import above re-exports it under this module's namespace.)


# --- Analysis Result Factory ---


class AnalysisResultFactory:
    """Factory for AnalysisResult instances."""

    @staticmethod
    def create(
        *,
        issue_number: int = 42,
        sections: list[Any] | None = None,
    ) -> AnalysisResult:
        from models import AnalysisResult as AR
        from models import AnalysisSection, AnalysisVerdict

        if sections is None:
            sections = [
                AnalysisSection(
                    name="File Validation",
                    verdict=AnalysisVerdict.PASS,
                    details=["All files exist."],
                ),
            ]
        return AR(
            issue_number=issue_number,
            sections=sections,
        )

    @staticmethod
    def create_section(
        *,
        name: str = "File Validation",
        verdict: Any | None = None,
        details: list[str] | None = None,
    ) -> Any:
        from models import AnalysisSection, AnalysisVerdict

        return AnalysisSection(
            name=name,
            verdict=verdict if verdict is not None else AnalysisVerdict.PASS,
            details=details if details is not None else [],
        )


# --- Test Scaffold Result Factory ---


class TestScaffoldResultFactory:
    """Factory for TestScaffoldResult instances."""

    __test__ = False

    @staticmethod
    def create(
        *,
        created_dirs: list[str] | None = None,
        created_files: list[str] | None = None,
        modified_files: list[str] | None = None,
        skipped: bool = False,
        skip_reason: str = "",
        language: str = "python",
    ) -> TestScaffoldResult:
        from test_scaffold import TestScaffoldResult

        return TestScaffoldResult(
            created_dirs=created_dirs if created_dirs is not None else [],
            created_files=created_files if created_files is not None else [],
            modified_files=modified_files if modified_files is not None else [],
            skipped=skipped,
            skip_reason=skip_reason,
            language=language,
        )


# --- CI Scaffold Result Factory ---


class CIScaffoldResultFactory:
    """Factory for CIScaffoldResult instances."""

    @staticmethod
    def create(
        *,
        created: bool = True,
        skipped: bool = False,
        skip_reason: str = "",
        language: str = "python",
        workflow_path: str = ".github/workflows/quality.yml",
    ) -> CIScaffoldResult:
        from ci_scaffold import CIScaffoldResult as CS

        return CS(
            created=created,
            skipped=skipped,
            skip_reason=skip_reason,
            language=language,
            workflow_path=workflow_path,
        )


# --- State Fixture ---


@pytest.fixture
def state(tmp_path: Path):
    from state import StateTracker

    return StateTracker(tmp_path / "state.json")


# --- State Factory ---


def make_state(tmp_path: Path) -> StateTracker:
    from state import StateTracker as ST

    return ST(tmp_path / "state.json")


# --- Event Bus Fixture ---


@pytest.fixture
def event_bus():
    from events import EventBus

    return EventBus()


# --- Orchestrator Mock ---


def make_orchestrator_mock(
    requests: dict | None = None,
    running: bool = False,
    run_status: str = "idle",
) -> MagicMock:
    orch = MagicMock()
    orch.human_input_requests = requests if requests is not None else {}
    orch.provide_human_input = MagicMock()
    orch.running = running
    orch.run_status = run_status
    orch.current_session_id = None
    orch.credits_paused_until = None
    orch.stop = AsyncMock()
    orch.request_stop = AsyncMock()
    orch.is_bg_worker_enabled = MagicMock(return_value=running)
    return orch


# --- Subprocess Mock ---


class SubprocessMockBuilder:
    """Fluent builder for mocking asyncio.create_subprocess_exec."""

    def __init__(self) -> None:
        self._returncode = 0
        self._stdout = b""
        self._stderr = b""

    def with_returncode(self, code: int) -> SubprocessMockBuilder:
        self._returncode = code
        return self

    def with_stdout(self, data: str | bytes) -> SubprocessMockBuilder:
        self._stdout = data.encode() if isinstance(data, str) else data
        return self

    def with_stderr(self, data: str | bytes) -> SubprocessMockBuilder:
        self._stderr = data.encode() if isinstance(data, str) else data
        return self

    def build(self) -> AsyncMock:
        """Build a mock for asyncio.create_subprocess_exec."""
        mock_proc = AsyncMock()
        mock_proc.returncode = self._returncode
        mock_proc.communicate = AsyncMock(return_value=(self._stdout, self._stderr))
        mock_proc.wait = AsyncMock(return_value=self._returncode)

        mock_create = AsyncMock(return_value=mock_proc)
        return mock_create


# --- Review Mock Builder ---


class ReviewMockBuilder:
    """Fluent builder for _review_prs test mocks."""

    def __init__(self, orch: HydraFlowOrchestrator, config: HydraFlowConfig) -> None:
        self._orch = orch
        self._config = config
        self._verdict: ReviewVerdict | None = None
        self._review_result: ReviewResult | None = None
        self._review_side_effect: Any = None
        self._merge_return: bool = True
        self._diff_text: str = "diff text"
        self._issue_number: int = 42
        self._pr_methods: dict[str, Any] = {}

    def with_verdict(self, verdict: ReviewVerdict) -> ReviewMockBuilder:
        self._verdict = verdict
        return self

    def with_review_result(self, result: ReviewResult) -> ReviewMockBuilder:
        self._review_result = result
        return self

    def with_review_side_effect(self, side_effect: Any) -> ReviewMockBuilder:
        self._review_side_effect = side_effect
        return self

    def with_merge_return(self, value: bool) -> ReviewMockBuilder:
        self._merge_return = value
        return self

    def with_issue_number(self, number: int) -> ReviewMockBuilder:
        self._issue_number = number
        return self

    def with_pr_method(self, name: str, mock: Any) -> ReviewMockBuilder:
        """Override a specific mock_prs method."""
        self._pr_methods[name] = mock
        return self

    def build(self) -> tuple[AsyncMock, AsyncMock, AsyncMock]:
        """Wire mocks into orch and return (mock_reviewers, mock_prs, mock_wt)."""
        from models import ReviewVerdict as RV

        # Reviewer mock
        mock_reviewers = AsyncMock()
        if self._review_side_effect:
            mock_reviewers.review = self._review_side_effect
        else:
            verdict = self._verdict if self._verdict is not None else RV.APPROVE
            result = self._review_result or ReviewResultFactory.create(
                pr_number=101,
                issue_number=self._issue_number,
                verdict=verdict,
                summary="Looks good.",
                fixes_made=False,
            )
            mock_reviewers.review = AsyncMock(return_value=result)
        self._orch._svc.reviewers = mock_reviewers

        # PR manager mock
        mock_prs = AsyncMock()
        mock_prs.get_pr_diff = AsyncMock(return_value=self._diff_text)
        mock_prs.push_branch = AsyncMock(return_value=True)
        mock_prs.merge_pr = AsyncMock(return_value=self._merge_return)
        mock_prs.remove_label = AsyncMock()
        mock_prs.add_labels = AsyncMock()
        mock_prs.post_pr_comment = AsyncMock()
        mock_prs.submit_review = AsyncMock(return_value=True)
        mock_prs.pull_main = AsyncMock()
        for name, mock in self._pr_methods.items():
            setattr(mock_prs, name, mock)
        self._orch._svc.prs = mock_prs

        # Worktree mock
        mock_wt = AsyncMock()
        mock_wt.destroy = AsyncMock()
        self._orch._svc.workspaces = mock_wt

        # Create worktree directory
        wt = self._config.workspace_base / f"issue-{self._issue_number}"
        wt.mkdir(parents=True, exist_ok=True)

        return mock_reviewers, mock_prs, mock_wt


def write_plugin_skill(
    cache_root: Path,
    marketplace: str,
    plugin: str,
    skill: str,
    *,
    name: str | None = None,
    description: str | None = None,
    frontmatter: str | None = None,
    version: str = "1.0.0",
) -> Path:
    """Create a SKILL.md under the real cache layout and return its path.

    Layout: ``<cache_root>/<marketplace>/<plugin>/<version>/skills/<skill>/SKILL.md``.
    Shared helper used by plugin-skill-registry and preflight-plugins tests.
    """
    skill_dir = cache_root / marketplace / plugin / version / "skills" / skill
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_md = skill_dir / "SKILL.md"
    if frontmatter is not None:
        content = f"---\n{frontmatter}\n---\n\nBody here.\n"
    else:
        content = (
            "---\n"
            f"name: {name or skill}\n"
            f"description: {description or f'{skill} description'}\n"
            "---\n\nBody here.\n"
        )
    skill_md.write_text(content)
    return skill_md


# --- time-travel guard (#11047) ----------------------------------------------


@pytest.fixture(autouse=True)
def _time_travel() -> Any:
    """Offset the wall clock when ``HYDRAFLOW_TIME_TRAVEL_DAYS`` is set (#11047).

    The wall-clock time-bomb class: a fixture hardcodes an absolute date (PR
    #11045) or freezes a ``_NOW`` anchor while the code under test reads the
    real ``datetime.now()`` (PR #11053), and silently ages past a now()-relative
    threshold — two RC-blocking detonations in 48 hours. This fixture is the
    detonator range: ``make time-travel`` re-runs the bomb-prone subset with the
    clock pushed N days forward, so any fixture whose semantics depend on the
    absolute date fails in the advisory lane instead of on a future RC.

    Inert unless the env var is set (zero cost in normal runs). ``tick=True``
    keeps the clock advancing from the offset instant so sleep/timeout logic
    behaves; freezegun leaves ``time.monotonic`` untouched, so asyncio timing
    is unaffected. Subprocesses see the real clock — the bombs live in-process,
    in fixture-vs-``datetime.now()`` comparisons.
    """
    days = os.environ.get("HYDRAFLOW_TIME_TRAVEL_DAYS")
    if not days:
        yield
        return
    from datetime import UTC, datetime, timedelta

    from freezegun import freeze_time

    target = datetime.now(UTC) + timedelta(days=int(days))
    with freeze_time(target, tick=True):
        yield
