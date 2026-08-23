"""The Fable director has no authority, and that is a property of the source (#11537).

#11537's second acceptance criterion is a list of things the director must not
be able to obtain: *"no Bash, arbitrary model string, credentials, label
mutation, merge action, or direct process spawn."* Most of that is already
closed by the contracts — ``WorkerRole`` has no tool axis, ``DirectorCommandKind``
has three members and none of them moves a label, ``WorkerDispatchRequest``
refuses a concrete model id, and ``DirectorCapsule`` forbids unknown fields.

What the contracts *cannot* stop is the director's own modules growing the
capability directly, and that is what these tests are for. They read the source
rather than the behaviour, because the claim being made is about absence and no
behavioural test can demonstrate the absence of a method that has not been
written yet.

``director_turn_runner`` is the one module that reaches a process at all, and
even it owns no spawn primitive: it delegates to the sanctioned
``SubprocessRunner.run_simple``, which carries the reap machinery ADR-0137 S6
requires. The last two tests pin that, and that its spawner is injected rather
than built inside a method.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.architecture.sandbox_seam_scan import SPAWN_PRIMITIVES

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Every module in the director's decision path. ``director_turn_runner`` is
#: deliberately absent: it is the module that reaches the CLI, and it has its
#: own two tests at the bottom of this file.
DECISION_PATH_MODULES = (
    "src/fable_director.py",
    "src/director_broker.py",
    "src/director_shadow_log.py",
    # #11541 added an actuator, and split it from its decision layer precisely
    # so the decision layer could stay on this list. ``plan_broker`` resolves
    # model tiers and owns the canary's bound; it must remain unable to spawn,
    # mutate a label, or touch convergence state. The one module that CAN reach
    # a process is ``plan_worker_runner``, which is seam-declared and has its
    # own tests at the bottom of this file.
    "src/plan_broker.py",
    # #11542 added a second actuator and split it the same way. ``implement_broker``
    # owns the Implement canary's bound, the writer-lease registry, the
    # hibernation predicate and the fence that makes a superseded worker's
    # result rejected — all pure, all on this list. The one module that CAN
    # reach a process is ``implement_worker_runner``, which is seam-declared and
    # has its own tests at the bottom of this file.
    "src/implement_broker.py",
)

#: Mutation calls that would give the director real authority over an issue.
#: Names, not types, because the point is that the call site must not exist —
#: a typed port would still be authority if it were reachable from here.
FORBIDDEN_MUTATIONS = frozenset(
    {
        "swap_pipeline_labels",
        "add_labels",
        "add_label",
        "remove_label",
        "remove_labels",
        "set_labels",
        "merge_pr",
        "merge_pull_request",
        "squash_merge",
        "enable_auto_merge",
        "create_pr",
        "create_pull_request",
        "close_issue",
        "post_comment",
        "create_comment",
    }
)

#: The broker's ENTIRE public surface. An allow-list, not a deny-list of
#: plausible verb names: a deny-list would pass ``admit_and_run``, ``submit``,
#: ``send``, ``fan_out`` or ``__call__``, which is precisely the fail-open shape
#: finding F2 condemns and which this repo refuses to reproduce inside the guard
#: that is meant to be the proof. Adding a method reddens this test, which is
#: the point: #11541 must widen the surface deliberately.
ALLOWED_BROKER_METHODS = frozenset({"admit"})


def _tree(relative: str) -> ast.Module:
    path = REPO_ROOT / relative
    return ast.parse(path.read_text(encoding="utf-8"), filename=relative)


def _called_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        if isinstance(callee, ast.Name):
            names.add(callee.id)
        elif isinstance(callee, ast.Attribute):
            names.add(callee.attr)
    return names


@pytest.mark.parametrize("module", DECISION_PATH_MODULES)
def test_the_decision_path_never_spawns_a_process(module: str) -> None:
    # The director's own turn is spawned by ``director_turn_runner``, which is
    # seam-declared. Nothing in the decision path may spawn anything at all —
    # that is the "no direct process spawn" half of the criterion.
    assert not (_called_names(_tree(module)) & SPAWN_PRIMITIVES)


@pytest.mark.parametrize("module", DECISION_PATH_MODULES)
def test_the_decision_path_never_mutates_a_label_or_merges(module: str) -> None:
    assert not (_called_names(_tree(module)) & FORBIDDEN_MUTATIONS)


def test_the_brokers_public_surface_is_exactly_admit() -> None:
    # The strongest available form of "no production worker is dispatched by
    # Fable": not a flag, not a guard, but the absence of the code — and stated
    # as an allow-list so a method nobody thought to forbid cannot slip past.
    from director_broker import ShadowDispatchBroker

    public = {
        name
        for name in vars(ShadowDispatchBroker)
        if not name.startswith("_") and callable(getattr(ShadowDispatchBroker, name))
    }

    assert public == ALLOWED_BROKER_METHODS


def test_the_broker_imports_nothing_that_could_run_a_worker() -> None:
    # A method name is only half of it: the capability would have to be
    # *reachable*, and the broker importing a runner, a port or a subprocess
    # module is the earliest visible sign that someone is about to make it so.
    tree = _tree("src/director_broker.py")
    imported = {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    } | {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }

    assert not (
        imported
        & {
            "subprocess",
            "asyncio",
            "execution",
            "ports",
            "runner_utils",
            "subprocess_util",
            "base_runner",
            "director_turn_runner",
        }
    )


def test_the_director_never_writes_convergence_state() -> None:
    # ADR-0137's narrowing of ADR-0094: ConvergenceLedger remains the sole owner
    # of convergence state, and a driver may sequence the outer lap but may not
    # own its state. A shadow director keeping its own parallel view of laps,
    # verdicts or open concerns would have broken the ADR that permits it.
    forbidden = {
        "increment_route_backs",
        "record_lap",
        "recompute_converged",
        "set_converged",
        "add_open_concern",
        "resolve_open_concern",
        "record_stage_transition",
        "record_sub_state_transition",
    }
    called: set[str] = set()
    for module in DECISION_PATH_MODULES:
        called |= _called_names(_tree(module))

    assert not (called & forbidden)


def test_the_broker_does_not_reimplement_the_admission_rule_table() -> None:
    # It must delegate to ``driver_contracts.admit_dispatch``. A second copy of
    # the rules would fork the vocabulary the canary's evidence bar counts
    # against, and the two copies would drift.
    assert "admit_dispatch" in _called_names(_tree("src/director_broker.py"))


def test_the_turn_runner_never_resumes_a_vendor_session() -> None:
    # Fresh reconstruction is an acceptance criterion, and it is met by never
    # having a session to lose. A ``--resume`` appearing in the argv would
    # silently convert that guarantee into a recovery path.
    # Matched on exact string constants rather than on the text of the file, so
    # the module can go on *explaining* why it never resumes without tripping
    # its own guard — a guard a maintainer has to fight is a guard that gets
    # deleted.
    flags = {
        node.value
        for node in ast.walk(_tree("src/director_turn_runner.py"))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }

    assert not {flag for flag in flags if flag.startswith("--resume")}


def test_the_turn_runner_owns_no_raw_spawn_primitive() -> None:
    # ADR-0137 S6 is satisfied by *delegation*, not by a hand-rolled reap. The
    # sanctioned ``SubprocessRunner.run_simple`` already spawns in its own
    # session, registers the child with the runtime reap registry, and calls
    # kill_process_group from both its TimeoutError and its CancelledError
    # handler. A raw spawn here would have to re-derive all of that, which is
    # the defect #11632 had to fix in the probe (``subprocess.run(timeout=...)``
    # kills only the direct child). ``test_subprocess_reap_guard.py`` enforces
    # the same rule fleet-wide; this pins it for the director specifically,
    # because the director is the one component with a legitimate reason to
    # want a raw spawn — it needs a *replaced* environment, not a merged one.
    assert not (_called_names(_tree("src/director_turn_runner.py")) & SPAWN_PRIMITIVES)


def test_the_plan_actuator_never_mutates_a_label_or_merges() -> None:
    # #11541 gives one module the ability to start a process. It must gain
    # nothing else: a brokered Plan worker produces an artifact and a receipt,
    # and the deterministic driver still owns every label and every merge.
    assert not (_called_names(_tree("src/plan_worker_runner.py")) & FORBIDDEN_MUTATIONS)


def test_the_plan_actuator_never_writes_convergence_state() -> None:
    # ADR-0137's narrowing of ADR-0094 survives dispatch being armed:
    # ConvergenceLedger stays the sole owner of convergence state, and the
    # canary's evidence is telemetry beside it rather than a second copy.
    forbidden = {
        "increment_route_backs",
        "record_lap",
        "recompute_converged",
        "set_converged",
        "add_open_concern",
        "resolve_open_concern",
        "record_stage_transition",
        "record_sub_state_transition",
    }

    assert not (_called_names(_tree("src/plan_worker_runner.py")) & forbidden)


def test_the_plan_actuator_owns_no_raw_spawn_primitive() -> None:
    # Same rule as the turn runner's, for the same reason: the sanctioned
    # ``run_lightweight_agent`` carries the CH-6 gate, the per-spawn mint and
    # revoke, the credit detection and the telemetry row. A raw spawn here
    # would have to re-derive all four and would get one wrong.
    raw = SPAWN_PRIMITIVES - {"run_lightweight_agent"}

    assert not (_called_names(_tree("src/plan_worker_runner.py")) & raw)


def test_the_plan_actuator_is_seam_declared() -> None:
    # It DOES lexically call ``run_lightweight_agent``, so the sandbox scan
    # sees it and a declaration is required rather than optional. Without the
    # row an air-gapped scenario could spawn a real Sonnet worker — the s51/s56
    # wedge class.
    from mockworld.sandbox_main import SANDBOX_SEAMS

    assert SANDBOX_SEAMS["plan_worker_runner"] == "config_disable"


def test_the_implement_actuator_never_mutates_a_label_or_merges() -> None:
    # #11542 gives a second module the ability to start a process, and this one
    # starts WRITE-capable roles. It must gain nothing else: a brokered
    # implementer or debugger produces an artifact and a receipt, and the
    # deterministic ImplementPhase still owns every commit and every label.
    called = _called_names(_tree("src/implement_worker_runner.py"))

    assert not (called & FORBIDDEN_MUTATIONS)


def test_the_implement_actuator_never_writes_convergence_state() -> None:
    # ADR-0137's narrowing of ADR-0094 survives a write-capable worker existing:
    # a driver may sequence the outer lap but may not own its state, and a
    # worker that started keeping a parallel view of laps or verdicts would
    # have broken the ADR that permits it.
    forbidden = {
        "increment_route_backs",
        "record_lap",
        "recompute_converged",
        "set_converged",
        "add_open_concern",
        "resolve_open_concern",
        "record_stage_transition",
        "record_sub_state_transition",
    }

    assert not (_called_names(_tree("src/implement_worker_runner.py")) & forbidden)


def test_the_implement_actuator_never_commits_or_pushes() -> None:
    # #11542's sixth acceptance criterion — "existing implementation output
    # markers, quality gates, commit rules, and no-push rule remain unchanged" —
    # as a property of what this module cannot reach, rather than as a promise
    # beside it. Names rather than types, because the point is that the call
    # site must not exist.
    forbidden = {
        "commit",
        "commit_all",
        "push_branch",
        "force_push",
        "create_commit",
        "stage_all",
        "write_text",
        "write_bytes",
    }

    assert not (_called_names(_tree("src/implement_worker_runner.py")) & forbidden)


def test_the_implement_actuator_owns_no_raw_spawn_primitive() -> None:
    # Same rule as the Plan actuator's: the sanctioned ``run_lightweight_agent``
    # carries the CH-6 gate, the per-spawn mint and revoke, the credit
    # detection and the telemetry row. The worktree measurement is deliberately
    # NOT on this list — it goes through the injected ``SubprocessRunner``,
    # which owns the reap machinery and which the sandbox replaces wholesale.
    raw = SPAWN_PRIMITIVES - {"run_lightweight_agent"}

    assert not (_called_names(_tree("src/implement_worker_runner.py")) & raw)


def test_the_implement_actuator_is_seam_declared() -> None:
    # It DOES lexically call ``run_lightweight_agent``, so the sandbox scan sees
    # it and a declaration is required rather than optional. Without the row an
    # air-gapped scenario could spawn a real write-capable worker — the s51/s56
    # wedge class, one degree worse than #11541's because these roles write.
    from mockworld.sandbox_main import SANDBOX_SEAMS

    assert SANDBOX_SEAMS["implement_worker_runner"] == "config_disable"


def test_the_sandbox_clears_the_implement_canary_dial() -> None:
    # A ``config_disable`` row is silently aspirational unless the pin exists.
    # #11541 declared one and wired it; this asserts #11542's is wired too,
    # rather than trusting that the row implies the override.
    source = (REPO_ROOT / "src/mockworld/sandbox_main.py").read_text(encoding="utf-8")

    assert '"fable_implement_canary_repo", ""' in source


async def test_the_implement_actuator_actually_uses_the_injected_git_runner() -> None:
    # Asserting the parameter merely *exists* would pass against a runner that
    # accepts it and shells out anyway, which is a seam in name only. So this
    # drives a real measurement and checks the injected double is what ran.
    from config import HydraFlowConfig
    from execution import SimpleResult
    from implement_broker import WriterLeaseRegistry
    from implement_worker_runner import ImplementWorkerRunner

    class RecordingRunner:
        def __init__(self) -> None:
            self.commands: list[list[str]] = []

        async def run_simple(self, cmd, **kwargs):
            self.commands.append(list(cmd))
            return SimpleResult(stdout="", stderr="", returncode=0)

    import tempfile
    from pathlib import Path as _Path

    with tempfile.TemporaryDirectory() as workspace:
        settings = HydraFlowConfig(
            state_file=_Path(workspace) / "state.json",
            repo="acme/widgets",
            workspace_base=_Path(workspace) / "worktrees",
        )
        settings.workspace_path_for_issue(7).mkdir(parents=True, exist_ok=True)
        probe = RecordingRunner()
        await ImplementWorkerRunner(
            config=settings,
            route_policy_revision="route-v1",
            runner=probe,  # type: ignore[arg-type]
            leases=WriterLeaseRegistry(),
            base_ref="origin/staging",
        ).measure(7)

    assert probe.commands and probe.commands[0][0] == "git"


async def test_the_turn_runner_actually_uses_the_injected_spawner() -> None:
    # Asserting the parameter merely *exists* would pass against a runner that
    # accepts it and ignores it, which is a seam in name only — and a seam in
    # name only is how the s51/s56/s57 sandbox wedges happened. So this drives
    # a turn and checks the injected double is what ran.
    from director_turn_runner import DirectorTurnRunner

    class RecordingRunner:
        def __init__(self) -> None:
            self.commands: list[list[str]] = []

        async def run_simple(self, cmd, **kwargs):
            from execution import SimpleResult

            self.commands.append(list(cmd))
            return SimpleResult(stdout="", stderr="", returncode=0)

    spawner = RecordingRunner()
    await DirectorTurnRunner(runner=spawner, cli_path="claude-double").run_turn("hi")

    assert spawner.commands and spawner.commands[0][0] == "claude-double"
