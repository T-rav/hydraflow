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
    # #11543 added a THIRD canary and split it the same way. ``review_broker``
    # owns the Review canary's bound, the REVIEW tier binding and the
    # independence fence that stops an implementer reviewing its own work — all
    # pure, all on this list. This is the boundary where "no authority" is the
    # whole point of the phase, so it is also the one where a prose claim would
    # be worth least. The module that CAN reach a process is
    # ``review_worker_runner``, which is seam-declared and covered by the
    # actuator table at the bottom of this file.
    "src/review_broker.py",
    # The other two P5 modules make the SAME claim in prose and were not on
    # this list, so nothing enforced it: ``review_evidence`` says "Pure by
    # construction: no I/O, no clock, no spawn" and ``review_authority`` says
    # "Merge authority is not modelled here at all". ``adjudicate`` is the one
    # P5 function that produces a ``ReviewVerdict``, so a
    # ``merge_pr`` added beside it was exactly the edit this guard exists to
    # redden — and would not have. Three modules claimed the property; one was
    # pinned (#11543).
    "src/review_evidence.py",
    "src/review_authority.py",
    # #11542 cut the actuator half out of ``fable_director`` when the mass
    # sensor flagged the host class. It moved with its guarantees: the mixin
    # decides which canary covers a boundary and hands an admitted batch to a
    # dispatcher, and it must remain unable to spawn, mutate a label, or touch
    # convergence state. Splitting a god class must not split a guard.
    "src/director_dispatch.py",
    # Surfaced by the DERIVED guard below rather than by anyone remembering:
    # `worker_receipts` says "no spawn" in its own docstring and was on no
    # list. It is where all three actuators build receipts, so a spawn or a
    # label mutation added beside `unresolved_decision` reaches the record
    # ADR-0137 B5's bar is read from.
    "src/worker_receipts.py",
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

#: Calls that would make an actuator an owner of convergence state. ADR-0137's
#: narrowing of ADR-0094 survives dispatch being armed and survives a
#: write-capable worker existing: a driver may sequence the outer lap but may
#: not own its state, and the canaries' evidence is telemetry beside the ledger
#: rather than a second copy of it.
CONVERGENCE_WRITES = frozenset(
    {
        "increment_route_backs",
        "record_lap",
        "recompute_converged",
        "set_converged",
        "add_open_concern",
        "resolve_open_concern",
        "record_stage_transition",
        "record_sub_state_transition",
    }
)

#: The broker's ENTIRE public surface. An allow-list, not a deny-list of
#: plausible verb names: a deny-list would pass ``admit_and_run``, ``submit``,
#: ``send``, ``fan_out`` or ``__call__``, which is precisely the fail-open shape
#: finding F2 condemns and which this repo refuses to reproduce inside the guard
#: that is meant to be the proof. Adding a method reddens this test, which is
#: the point: #11541 must widen the surface deliberately.
ALLOWED_BROKER_METHODS = frozenset({"admit"})


#: The exact sentence a decision-path module carries in its own module
#: docstring, and the thing ``DECISION_PATH_MODULES`` is derived from.
#:
#: The needle it replaces was ``"no spawn" in doc.lower()``, which matched
#: FOUR of the ten entries (#11723 F2). Deleting ``src/plan_broker.py`` or
#: ``src/review_authority.py`` from the list above reddened nothing, because
#: neither uses that phrase — a predicate merely *correlated* with the subject,
#: standing in for the subject. This sentence is carried by exactly the ten,
#: so the derivation is TOTAL for the literal and the two are asserted equal.
#:
#: Deliberately a sentence no module would write by accident. A looser needle
#: is how the previous one degenerated; a needle a module must opt into is how
#: ``literal == derived`` stays an equality rather than a containment.
DECISION_PATH_CLAIM = "Decision path, no authority."


def claiming_modules() -> frozenset[str]:
    """Every ``src`` module that declares itself on the decision path.

    The derivation, resolved from source on every run. Public because
    ``guard_enumeration_registry`` witnesses drops from
    ``DECISION_PATH_MODULES`` by calling THIS function rather than a copy of
    it: a gate that re-implements the derivation it is checking is checking
    its own copy.
    """
    found: set[str] = set()
    for path in sorted((REPO_ROOT / "src").rglob("*.py")):
        try:
            doc = ast.get_docstring(ast.parse(path.read_text(errors="replace"))) or ""
        except SyntaxError:  # pragma: no cover - a broken module fails elsewhere
            continue
        if DECISION_PATH_CLAIM in doc:
            found.add(str(path.relative_to(REPO_ROOT)))
    return frozenset(found)


def module_tree(relative: str) -> ast.Module:
    path = REPO_ROOT / relative
    return ast.parse(path.read_text(encoding="utf-8"), filename=relative)


def called_names(tree: ast.Module) -> set[str]:
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


def import_roots(tree: ast.Module) -> set[str]:
    """Top-level package of every absolute import in *tree*.

    Public because ``guard_enumeration_registry`` witnesses ``_SPAWN_MACHINERY``
    by feeding this extractor a subject module with an import injected. A
    re-implementation there would be a second copy of the rule, and the two
    would drift — which is the shape ``docs/standards/parametrised_guards``
    exists to stop.
    """
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


@pytest.mark.parametrize("module", DECISION_PATH_MODULES)
def test_the_decision_path_never_spawns_a_process(module: str) -> None:
    # The director's own turn is spawned by ``director_turn_runner``, which is
    # seam-declared. Nothing in the decision path may spawn anything at all —
    # that is the "no direct process spawn" half of the criterion.
    assert not (called_names(module_tree(module)) & SPAWN_PRIMITIVES)


@pytest.mark.parametrize("module", DECISION_PATH_MODULES)
def test_the_decision_path_never_mutates_a_label_or_merges(module: str) -> None:
    assert not (called_names(module_tree(module)) & FORBIDDEN_MUTATIONS)


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
    tree = module_tree("src/director_broker.py")
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
    # The set is ``CONVERGENCE_WRITES``, defined once below rather than
    # restated here. The literal that used to sit inline was a second copy of
    # one vocabulary: the two were byte-identical on the day they were written
    # and nothing kept them so, which is how a name added to one and not the
    # other stops being forbidden on half the boundary (#11723).
    called: set[str] = set()
    for module in DECISION_PATH_MODULES:
        called |= called_names(module_tree(module))

    assert not (called & CONVERGENCE_WRITES)


def test_the_broker_does_not_reimplement_the_admission_rule_table() -> None:
    # It must delegate to ``driver_contracts.admit_dispatch``. A second copy of
    # the rules would fork the vocabulary the canary's evidence bar counts
    # against, and the two copies would drift.
    assert "admit_dispatch" in called_names(module_tree("src/director_broker.py"))


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
        for node in ast.walk(module_tree("src/director_turn_runner.py"))
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
    assert not (
        called_names(module_tree("src/director_turn_runner.py")) & SPAWN_PRIMITIVES
    )


#: Every module that can start a brokered child, and the ``SANDBOX_SEAMS`` key
#: it must be declared under. A TABLE rather than three hand-written copies per
#: rule: #11543 was about to add a third set of near-identical tests, and the
#: suite-hygiene ratchet is right that the copies are the defect — a fourth
#: canary should be one row here, and should be unable to exist without one.
ACTUATORS: tuple[tuple[str, str], ...] = (
    ("src/plan_worker_runner.py", "plan_worker_runner"),
    ("src/implement_worker_runner.py", "implement_worker_runner"),
    ("src/review_worker_runner.py", "review_worker_runner"),
)


def brokered_actuator_modules() -> frozenset[str]:
    """Every ``src`` module whose name declares it a brokered actuator.

    The derivation ``ACTUATORS`` is pinned against. A canary's actuator is
    ``src/<phase>_worker_runner.py`` by construction — the naming is the
    convention #11541 set and #11542/#11543 followed — so the table has a free
    derivation and does not need anyone to remember the row (#11723).

    Public for the same reason :func:`claiming_modules` is: the enumeration
    gate calls this, not a copy of it.
    """
    return frozenset(
        str(path.relative_to(REPO_ROOT))
        for path in sorted((REPO_ROOT / "src").glob("*_worker_runner.py"))
    )


def test_the_actuator_table_and_the_naming_convention_are_the_same_set() -> None:
    """The DROPS direction of ``ACTUATORS`` (#11723).

    Dropping the ``review_worker_runner`` row silently un-guarded THREE
    parametrised checks against the module that spawns the reviewer, and
    reddened nothing — the table was iterated by its own tests and by nothing
    else. The derivation was free the whole time.

    Equality, not containment, so both edits redden: removing a row while the
    file exists, and adding a ``*_worker_runner.py`` without a row.
    """
    derived = brokered_actuator_modules()
    listed = frozenset(module for module, _seam in ACTUATORS)

    assert derived, (
        "no src/*_worker_runner.py exists; the derivation has no subject and "
        "every containment against it is vacuously true"
    )
    assert derived == listed, (
        "the actuator table and the naming convention disagree. "
        f"On disk but unlisted (spawns with no guard): {sorted(derived - listed)}. "
        f"Listed but gone from disk: {sorted(listed - derived)}."
    )


@pytest.mark.parametrize(("module", "_seam"), ACTUATORS)
def test_an_actuator_never_mutates_a_label_or_merges(module: str, _seam: str) -> None:
    # Each canary gives one module the ability to start a process. It must gain
    # nothing else: a brokered worker produces an artifact and a receipt, and
    # the deterministic driver still owns every label and every merge. #11542's
    # workers WRITE and #11543's has an opinion about whether a change should
    # land, so the rule matters more with each one, not less.
    assert not (called_names(module_tree(module)) & FORBIDDEN_MUTATIONS)


@pytest.mark.parametrize(("module", "_seam"), ACTUATORS)
def test_an_actuator_owns_no_raw_spawn_primitive(module: str, _seam: str) -> None:
    # Same rule as the turn runner's, for the same reason: the sanctioned
    # ``run_lightweight_agent`` carries the CH-6 gate, the per-spawn mint and
    # revoke, the credit detection and the telemetry row. A raw spawn here
    # would have to re-derive all four and would get one wrong. The Implement
    # actuator's worktree measurement is deliberately NOT caught by this — it
    # goes through the injected ``SubprocessRunner``, which owns the reap
    # machinery and which the sandbox replaces wholesale.
    raw = SPAWN_PRIMITIVES - {"run_lightweight_agent"}

    assert not (called_names(module_tree(module)) & raw)


@pytest.mark.parametrize(("module", "seam"), ACTUATORS)
def test_an_actuator_is_seam_declared(module: str, seam: str) -> None:
    # Each DOES lexically call ``run_lightweight_agent``, so the sandbox scan
    # sees it and a declaration is required rather than optional. Without the
    # row an air-gapped scenario could spawn a real worker — the s51/s56 wedge
    # class, one degree worse at IMPLEMENT because those roles write.
    from mockworld.sandbox_main import SANDBOX_SEAMS

    assert module.endswith(f"{seam}.py")
    assert SANDBOX_SEAMS[seam] == "config_disable"


@pytest.mark.parametrize(
    "dial",
    [
        pytest.param("fable_plan_canary_repo", id="plan"),
        pytest.param("fable_implement_canary_repo", id="implement"),
        pytest.param("fable_review_canary_repo", id="review"),
    ],
)
def test_the_sandbox_clears_every_canary_dial(dial: str, tmp_path) -> None:
    """A ``config_disable`` row is silently aspirational unless the pin exists.

    Asserted by **running the override**, not by matching its source text. The
    first version grepped for ``'"fable_implement_canary_repo", ""'``, which is
    a gate that stops seeing its subject the moment the line is reformatted,
    moved into a helper, or rewritten to the same effect — the exact class
    #11665 found twice (``CRITICAL_PATHS`` entries naming files that never
    existed, and regression tests monkeypatching a module that never existed,
    both staying green). This one calls the function and reads the dial.

    The DIAL, not ``fable_*_canary_armed()``. The first behavioural draft
    asserted the predicate and survived deleting the override outright, because
    the sandbox also pins ``execution_runtime`` — so the runtime pin answered
    False and the dial was never consulted. A defence behind the subject doing
    the subject's work is the same masking #11541's mutation testing found
    twice, and it is why this reads the one field the override actually writes.
    """
    from config import HydraFlowConfig
    from mockworld.sandbox_main import _apply_sandbox_config_overrides
    from scheduling_model import ExecutionRuntime, SchedulingModel

    fields: dict[str, object] = {
        "state_file": tmp_path / "state.json",
        "repo": "acme/widgets",
        "scheduling_model": SchedulingModel.ISSUE_CONTROLLER,
        "execution_runtime": ExecutionRuntime.FABLE_DIRECTOR,
        dial: "acme/widgets",
    }
    armed = HydraFlowConfig(**fields)

    _apply_sandbox_config_overrides(armed)

    assert getattr(armed, dial) == ""


#: Calls that would let a worker's output become the commit. #11542's sixth
#: acceptance criterion — "existing implementation output markers, quality
#: gates, commit rules, and no-push rule remain unchanged" — as a property of
#: what the module cannot reach rather than a promise beside it. Names rather
#: than types, because the point is that the call site must not exist.
WRITE_PRIMITIVES = frozenset(
    {
        "commit",
        "commit_all",
        "push_branch",
        "force_push",
        "create_commit",
        "stage_all",
        "write_text",
        "write_bytes",
    }
)


@pytest.mark.parametrize(
    ("module", "forbidden"),
    [
        pytest.param(
            "src/plan_worker_runner.py", CONVERGENCE_WRITES, id="plan-convergence"
        ),
        pytest.param(
            "src/implement_worker_runner.py",
            CONVERGENCE_WRITES,
            id="implement-convergence",
        ),
        pytest.param(
            "src/implement_worker_runner.py", WRITE_PRIMITIVES, id="implement-writes"
        ),
        pytest.param(
            "src/review_worker_runner.py", CONVERGENCE_WRITES, id="review-convergence"
        ),
        # The Review actuator is on the WRITE list too, although its catalogued
        # roles are read-only. The catalogue is a table an edit can change; this
        # is a property of what the module can reach, and it is what stops a
        # future "let the reviewer apply its own fix" being a one-line change
        # nothing reddens.
        pytest.param(
            "src/review_worker_runner.py", WRITE_PRIMITIVES, id="review-writes"
        ),
    ],
)
def test_an_actuator_reaches_no_forbidden_call(
    module: str, forbidden: frozenset[str]
) -> None:
    assert not (called_names(module_tree(module)) & forbidden)


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


def test_the_review_actuator_cannot_reach_the_adjudicator() -> None:
    """The one thing this actuator must not be able to do that its siblings
    have no equivalent of: turn a proposal into a verdict.

    ``review_authority.adjudicate`` is the only P5 function that produces a
    ``ReviewVerdict``, and a reviewer that could call it would own the decision
    whatever the prose around it said. Read from the AST rather than the text,
    so the docstrings *explaining* the rule cannot satisfy the test for it.
    """
    tree = module_tree("src/review_worker_runner.py")
    imported = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }

    assert "adjudicate" not in imported
    assert "ReviewVerdict" not in imported
    assert "adjudicate" not in called_names(tree)


def test_every_module_claiming_purity_is_on_the_list() -> None:
    """The DROPS direction of ``DECISION_PATH_MODULES`` (#11543).

    Every guard in this file checks that a LISTED module does nothing
    forbidden. Nothing checked that a module which *should* be listed is —
    so deleting an entry reddened nothing, and the guard silently stopped
    covering whatever was removed. That is the same asymmetry as
    ``as_payload`` testing only additions and the prompt test pinning "and
    nothing else" but never "from evidence": three sites, one class.

    The subject is DERIVED from the source, not enumerated here, per the rule
    this chain kept breaking: a fix written against a finding's prose inherits
    the prose's scope. A module that states the claim in its own docstring is
    held to it, and one added tomorrow is held to it too.

    Scope, stated exactly: the needle is the "no spawn" phrase, so it holds
    modules to the claim they actually make. ``review_authority`` is on the
    list for a different claim ("merge authority is not modelled here at all")
    and is deliberately outside this guard's subject — widening the needle to
    "pure" matches 88 modules and would turn the list into a directory.

    It found ``worker_receipts`` on its first run — a module that claims "no
    spawn", is where all three actuators build receipts, and had no test file
    of any kind (#11718).
    """
    claimants = []
    for path in sorted((REPO_ROOT / "src").rglob("*.py")):
        try:
            doc = ast.get_docstring(ast.parse(path.read_text(errors="replace"))) or ""
        except SyntaxError:  # pragma: no cover - a broken module fails elsewhere
            continue
        if "no spawn" in doc.lower():
            claimants.append(str(path.relative_to(REPO_ROOT)))

    assert claimants, "no module claims purity — this guard has no subject"

    missing = sorted(set(claimants) - set(DECISION_PATH_MODULES))
    assert not missing, (
        "these modules claim 'no spawn' in their own docstring but are absent "
        f"from DECISION_PATH_MODULES, so nothing enforces the claim: {missing}. "
        "Add them, or stop making the claim."
    )


def test_the_declared_claim_and_the_list_are_the_same_set() -> None:
    """The DROPS direction, closed (#11723 F2).

    The guard above is a containment — ``claimants ⊆ list`` — over a needle
    that matched four of the ten entries, so six of the ten could be deleted
    and nothing reddened. This is the equality, over a needle every entry
    carries: delete a row from ``DECISION_PATH_MODULES`` and the module still
    declares itself, so ``derived - literal`` is non-empty; delete the
    sentence from a module and ``literal - derived`` is. Neither edit is green
    on its own any more, which is what "two individually-green edits removed a
    module from every guard in this file" needed.

    The subject is the literal tuple BY REFERENCE, not a re-typed copy and not
    a predicate that selects from it — ``docs/standards/parametrised_guards``.
    """
    derived = claiming_modules()
    listed = frozenset(DECISION_PATH_MODULES)

    assert derived, (
        f"no module carries {DECISION_PATH_CLAIM!r}; the derivation has no "
        "subject and every containment below it is vacuously true"
    )
    assert derived == listed, (
        "the decision path's declaration and its enumeration disagree. "
        f"Declared but unlisted (nothing guards them): {sorted(derived - listed)}. "
        f"Listed but no longer declaring (the list is guarding a claim the "
        f"module withdrew): {sorted(listed - derived)}."
    )


#: Raw spawn machinery. ``SPAWN_PRIMITIVES`` names HydraFlow's *sanctioned*
#: helpers, and the repo-wide raw-spawn ratchet knows
#: ``create_subprocess_exec``/``Popen``/``spawnv`` — so a plain
#: ``subprocess.run(...)`` in a decision-path module passed BOTH (#11543).
#: Verified: injecting ``run_subprocess`` reddens, injecting ``subprocess.run``
#: did not. For ten modules that each claim purity, importing the machinery at
#: all is the rule with no false positives; a synchronous blocking spawn on an
#: async decision path is worse than the async one, not better.
_SPAWN_MACHINERY: frozenset[str] = frozenset({"subprocess", "multiprocessing"})


@pytest.mark.parametrize("module", DECISION_PATH_MODULES)
def test_the_decision_path_does_not_even_import_spawn_machinery(module: str) -> None:
    reached = import_roots(module_tree(module)) & _SPAWN_MACHINERY
    assert not reached, (
        f"{module} imports {sorted(reached)}. Every module on this list says it "
        "does not spawn; the call-site guards only know the sanctioned helper "
        "names and three raw signatures, so a plain subprocess.run() reaches "
        "neither. A module that needs to spawn belongs behind a declared seam."
    )


#: Attribute names on the ``os`` module that reach a process (#11724).
#:
#: ``called_names`` above flattens ``mod.f(...)`` to ``f``, and that flattening
#: is *why* the rule that does the work had to be on imports: ``run``,
#: ``system`` and ``popen`` are far too common as BARE attribute names to
#: sweep. That reasoning does not extend to an ``ast.Attribute`` whose value is
#: the Name ``os`` — ``os.system(...)`` is unambiguous — and ``os`` is
#: deliberately absent from ``_SPAWN_MACHINERY`` because every module on
#: ``DECISION_PATH_MODULES`` legitimately imports it for ``environ`` and paths.
#: So the ``os``-qualified call was the one shape neither rule saw, and no
#: other gate in the repo covered it either: bandit rates ``os.system`` B605
#: *Low* while the Makefile gates at *medium*, ruff does not select ``S``, and
#: ``SPAWN_PRIMITIVES`` names only HydraFlow's sanctioned helpers. Four gates,
#: four different reasons, one hole.
#:
#: PREFIXES rather than an enumeration, per the rule this chain keeps
#: relearning: a fix written against a finding's prose inherits the prose's
#: scope. #11724 named five attributes; ``os`` offers about twenty ways to
#: reach a process. Nothing in ``os`` beginning ``exec``/``spawn``/
#: ``posix_spawn``/``popen``/``fork`` is anything OTHER than a way to reach
#: one, so the prefix is exact here and covers ``execvpe``, ``spawnlpe`` and
#: ``posix_spawnp`` without anyone remembering to add them.
#:
#: ``fork`` is included although the repo-wide raw-spawn ratchet deliberately
#: excludes it — "fork" is a GitHub-domain verb in this codebase, so a BARE
#: ``.fork()`` would be a false positive there. Requiring the ``os`` qualifier
#: is exactly what makes it safe to include here.
#: A frozenset rather than the tuple ``str.startswith`` wants, on purpose:
#: ``guard_enumeration_registry.declared_deny_lists`` derives the deny-lists it
#: floors from the module-level frozensets of strings in this file, so a tuple
#: here would be a name-set of exactly the same kind sitting outside the
#: mechanism that protects the other five. Spelling it as a frozenset is what
#: makes ``DENY_LIST_FLOORS`` notice it; the ``tuple(...)`` at the call site is
#: the whole cost.
_OS_SPAWN_PREFIXES: frozenset[str] = frozenset(
    {
        "exec",
        "fork",
        "popen",
        "posix_spawn",
        "spawn",
    }
)

#: ``os`` spawn attributes with no useful prefix. ``startfile`` is Windows-only
#: and cannot appear on this repo's hosts, but the guard reads the SOURCE, not
#: the platform: deriving the subject from ``dir(os)`` would make the rule
#: depend on which OS ran the test, which is the host-dependence class this
#: repo has been bitten by before.
_OS_SPAWN_EXACT: frozenset[str] = frozenset({"system", "startfile"})


def _is_os_spawn(attr: str) -> bool:
    return attr in _OS_SPAWN_EXACT or attr.startswith(tuple(_OS_SPAWN_PREFIXES))


def _os_aliases(tree: ast.Module) -> set[str]:
    """Local names bound to the ``os`` MODULE in *tree*.

    Resolved rather than assumed, so ``import os as _o`` followed by
    ``_o.system(...)`` cannot walk out of the guard by renaming. ``import
    os.path`` binds the root ``os`` too; ``import os.path as p`` binds ``p`` to
    the SUBmodule, which owns no spawn attribute, so it is deliberately not
    treated as an alias for ``os``.
    """
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Import):
            continue
        for alias in node.names:
            if alias.name.split(".")[0] != "os":
                continue
            if alias.asname is None:
                aliases.add("os")
            elif alias.name == "os":
                aliases.add(alias.asname)
    return aliases


def reachable_os_spawns(tree: ast.Module) -> set[str]:
    """Every way *tree* reaches a process through ``os``, as dotted names.

    Matched on the ATTRIBUTE, not on the call. Requiring call position would
    have left ``s = os.system`` followed by ``s(...)`` — and ``@os.system`` —
    passing, and a rebinding reads as an ordinary diff in exactly the way
    #11724 is about. Referencing one of these attributes at all is the signal;
    a decision-path module has no legitimate reason to name one, called or not.

    Two shapes, because closing only the first leaves a one-line evasion:

    * an ``os``-qualified reference — ``os.system(...)``, ``_o.popen``;
    * a ``from os import system`` binding, whose call site is then a bare name
      the flattening detector cannot tell from any other ``system``. Caught at
      the import instead, where it is unambiguous.

    Stated limits, because an overstated guard is the defect this exists to
    fix. NOT caught: dynamic dispatch (``getattr(os, "system")(...)``,
    ``__import__("os").system(...)``, ``eval``). A lexical AST scan cannot see
    those, and unlike a plain ``os.system(...)`` they do not read as an
    ordinary diff — which was #11724's actual complaint. The negative control
    below pins that limit as a row rather than leaving it to prose.
    """
    aliases = _os_aliases(tree)
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            if (
                isinstance(node.value, ast.Name)
                and node.value.id in aliases
                and _is_os_spawn(node.attr)
            ):
                found.add(f"{node.value.id}.{node.attr}")
        elif (
            isinstance(node, ast.ImportFrom) and node.module == "os" and node.level == 0
        ):
            found.update(
                f"os.{alias.name}" for alias in node.names if _is_os_spawn(alias.name)
            )
    return found


@pytest.mark.parametrize("module", DECISION_PATH_MODULES)
def test_the_decision_path_cannot_reach_a_process_through_os(module: str) -> None:
    reached = reachable_os_spawns(module_tree(module))
    assert not reached, (
        f"{module} reaches a process through {sorted(reached)}. Every module on "
        "this list says in its own docstring that it does not spawn, and until "
        "#11724 this was the shape that said it while passing every gate in the "
        "repo: the import rule permits `os` on purpose, the call-site guard "
        "flattens `os.system` to `system`, bandit rates it B605 Low under a "
        "medium gate, and ruff does not select S. A module that needs to spawn "
        "belongs behind a declared seam."
    )


def test_the_os_spawn_subject_is_not_empty() -> None:
    """A detector with nothing to match must not pass silently.

    ``_OS_SPAWN_PREFIXES`` and ``_OS_SPAWN_EXACT`` are the entire subject of
    ``reachable_os_spawns``. Empty either pair and the function becomes one
    that always returns the empty set — the guard above it goes green over a
    module that really does spawn, which is #11724 restored with the fix still
    in the file. Nothing else in this repo reads these two names, so nothing
    else can notice.

    Scoped deliberately to that. The companion question — "is
    ``DECISION_PATH_MODULES`` still populated, and do its entries still
    exist?" — is NOT asserted here: ``test_the_declared_claim_and_the_list_are_the_same_set``
    already fails closed on both, so an assertion here would be satisfied by an
    upstream pin and deleting it would redden nothing. Verified by mutation,
    not assumed. That is the ``docs/standards/parametrised_guards`` known limit
    about unfalsifiable defences, applied to this file.
    """
    assert _OS_SPAWN_PREFIXES, "no os-spawn prefixes — reachable_os_spawns cannot fire"
    assert _OS_SPAWN_EXACT, "no exact os-spawn names — reachable_os_spawns is blind"


#: Every raw-spawn shape a decision-path module could reach for, the source it
#: would have to contain, and the NAME of the rule that catches it — measured
#: against a victim file by the test below, never asserted from prose.
#:
#: The version this table replaces parametrised over four bare strings and
#: never invoked a guard: both of its assertions were properties of its own
#: hardcoded input, and the ``| {"os"}`` in the second was precisely what let
#: the two then-UNCAUGHT ``os`` forms read as coverage (#11724).
#:
#: Three rules can fire, and the row names which one must:
#:
#: * ``"import"`` — ``_SPAWN_MACHINERY``. Reaching ``subprocess`` at all
#:   requires importing it, so the import is the cheapest true signal.
#: * ``"os"`` — ``reachable_os_spawns``. The qualified form, added by #11724.
#: * ``None`` — nothing here fires. A hole, recorded as a row so it cannot be
#:   mistaken for coverage; closing it reddens this table, which is the prompt
#:   to update it.
#:
#: ``"call-site"`` (``SPAWN_PRIMITIVES``) is a fourth possible value and no row
#: expects it: that guard knows only HydraFlow's sanctioned helper names. It is
#: still measured, so the day ``run`` or ``system`` becomes a sanctioned
#: primitive this test says so instead of quietly double-covering.
_RAW_SPAWNS: tuple[tuple[str, str, str, str | None], ...] = (
    (
        "popen-via-subprocess",
        "import subprocess",
        "subprocess.Popen(['true'])",
        "import",
    ),
    ("run-via-subprocess", "import subprocess", "subprocess.run(['true'])", "import"),
    ("os-system", "import os", "os.system('true')", "os"),
    ("os-popen", "import os", "os.popen('true')", "os"),
    ("os-execv", "import os", "os.execv('/bin/true', ['true'])", "os"),
    ("os-spawnl", "import os", "os.spawnl(os.P_WAIT, '/bin/true', 'true')", "os"),
    # The three evasions a name-based rule invites, pinned so closing the
    # qualified CALL cannot be mistaken for closing the shape. The rebound row
    # is why the detector matches the attribute rather than the call: `s(...)`
    # is a bare name by the time it is invoked.
    ("os-aliased", "import os as _o", "_o.system('true')", "os"),
    ("os-from-import", "from os import system", "system('true')", "os"),
    ("os-rebound", "import os\n\n_s = os.system", "_s('true')", "os"),
    # The stated limit. A lexical AST scan cannot follow dynamic dispatch, and
    # this row is the executable form of saying so.
    ("os-getattr", "import os", "getattr(os, 'system')('true')", None),
)


@pytest.mark.parametrize(("_id", "imports", "statement", "rule"), _RAW_SPAWNS)
def test_a_raw_spawn_is_caught_by_exactly_the_rule_the_table_names(
    _id: str, imports: str, statement: str, rule: str | None, tmp_path: Path
) -> None:
    """Negative control: run the real detectors over a module that really spawns.

    Writes a victim file — the shape ``test_vitals_conformance_seam.py`` uses —
    and asserts which rules actually fire, rather than restating the detectors'
    inputs back to themselves.
    """
    victim = tmp_path / "victim.py"
    victim.write_text(
        f"{imports}\n\n\ndef reach_a_process() -> None:\n    {statement}\n",
        encoding="utf-8",
    )
    tree = ast.parse(victim.read_text(encoding="utf-8"), filename=str(victim))

    fired = set()
    if import_roots(tree) & _SPAWN_MACHINERY:
        fired.add("import")
    if reachable_os_spawns(tree):
        fired.add("os")
    if called_names(tree) & SPAWN_PRIMITIVES:
        fired.add("call-site")

    expected = {rule} if rule else set()
    assert fired == expected, (
        f"{statement} fires {sorted(fired) or 'nothing'}; _RAW_SPAWNS says it "
        f"must fire {sorted(expected) or 'nothing'}. If a rule was widened on "
        "purpose, update the table — a row that overstates coverage is the "
        "defect #11724 was filed for."
    )
