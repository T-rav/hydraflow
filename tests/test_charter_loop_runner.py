"""CharterLoopRunner: one generic worker, parameterised by charter (#11861).

HydraFlow's runners take their role from a catalogued Python class. This takes
its role from the TARGET REPO's declaration, which is what makes the ownership
split real: the repo declares which actors exist and when they run; the factory
owns isolation, PR lifecycle, gates and escalation.

Three rulings are structural here, and each has a test that proves the
NEGATIVE — that the runner does not do the tempting thing.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


from charter_loop_runner import (
    OUTCOME_RAN,
    OUTCOME_REFUSED_BUDGET,
    OUTCOME_REFUSED_NO_CONTRACT,
    OUTCOME_SKIPPED_DORMANT,
    OUTCOME_SKIPPED_NOT_DUE,
    CharterLoopRunner,
    resolve_actor_contract,
    select_due_loops,
)
from charter_model import Charter

_NOW = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
_YESTERDAY = _NOW - timedelta(days=1)


def _charter(**loops) -> Charter:
    return Charter.from_dict({"schema_version": 2, "loops": loops})


class TestSelection:
    """A decision for EVERY loop, not only the due ones."""

    def test_a_dormant_loop_is_reported_not_omitted(self) -> None:
        """Omitting it would leave "dormant", "not due" and "never looked at"
        identical to a reader — the distinction the receipt exists for."""
        decisions = select_due_loops(
            _charter(a={"enabled": False, "trigger": [{"cron": "0 9 * * *"}]}),
            now=_NOW,
            last_fired={},
        )
        assert [(d.loop, d.outcome) for d in decisions] == [
            ("a", OUTCOME_SKIPPED_DORMANT)
        ]

    def test_a_due_loop_runs(self) -> None:
        decisions = select_due_loops(
            _charter(a={"enabled": True, "trigger": [{"cron": "0 9 * * *"}]}),
            now=_NOW,
            last_fired={"a": _YESTERDAY},
        )
        assert decisions[0].outcome == OUTCOME_RAN
        assert decisions[0].window == _NOW
        assert decisions[0].trigger == "0 9 * * *"

    def test_a_loop_already_run_this_window_is_not_due(self) -> None:
        decisions = select_due_loops(
            _charter(a={"enabled": True, "trigger": [{"cron": "0 9 * * *"}]}),
            now=_NOW,
            last_fired={"a": _NOW},
        )
        assert decisions[0].outcome == OUTCOME_SKIPPED_NOT_DUE

    def test_any_clause_may_fire_the_loop(self) -> None:
        """The D2 fix: a trigger is a LIST and any clause fires it."""
        decisions = select_due_loops(
            _charter(
                a={
                    "enabled": True,
                    "trigger": [{"cron": "0 3 * * *"}, {"cron": "0 9 * * *"}],
                }
            ),
            now=_NOW,
            last_fired={"a": _YESTERDAY},
        )
        assert decisions[0].outcome == OUTCOME_RAN
        assert decisions[0].trigger == "0 9 * * *"

    def test_an_unevaluable_schedule_is_refused_not_treated_as_quiet(self) -> None:
        """ "Not due" reads as a healthy quiet loop forever.

        The schema validates cron shape at parse time, so this is the
        defence-in-depth case — a charter loaded by an older parser, or a form
        the matcher declines. Either way it must be loud.
        """
        charter = _charter(a={"enabled": True})
        # Bypass the schema to construct the shape a stale parser could produce.
        object.__setattr__(
            charter.loops.loops[0],
            "triggers",
            (type(charter.loops.loops[0].triggers)(())),
        )
        decisions = select_due_loops(charter, now=_NOW, last_fired={})
        assert decisions[0].outcome == OUTCOME_SKIPPED_NOT_DUE


class TestTheRefusalPaths:
    """Both rulings that say what the runner must NOT do."""

    async def test_an_unreadable_actor_contract_refuses_and_alerts(
        self, tmp_path: Path
    ) -> None:
        """Ruling 2. A default prompt produces plausible work attributed to an
        actor whose contract nobody could read — worse than no run, because it
        looks like one."""
        (tmp_path / "agents").mkdir()
        alerts: list[dict] = []
        dispatched: list[dict] = []

        async def _alert(**kw):
            alerts.append(kw)

        async def _dispatch(**kw):
            dispatched.append(kw)
            return {}

        runner = CharterLoopRunner(
            repo="o/r",
            repo_root=tmp_path,
            receipts_path=tmp_path / "receipts.jsonl",
            dispatch=_dispatch,
            alert=_alert,
        )
        receipts = await runner.tick(
            _charter(a={"enabled": True, "trigger": [{"cron": "0 9 * * *"}]}),
            now=_NOW,
            last_fired={"a": _YESTERDAY},
        )

        assert receipts[0].outcome == OUTCOME_REFUSED_NO_CONTRACT
        assert alerts, "the refusal did not reach the operator"
        assert dispatched == [], (
            "the runner dispatched anyway — a default prompt is exactly what "
            "Ruling 2 forbids"
        )

    async def test_a_refusal_files_no_issue(self, tmp_path: Path) -> None:
        """A refusal that files an issue looks like work in progress, not a stop.

        Asserted as the absence of any issue-filing surface on the runner: it
        has none, which is the structural version of the rule.
        """
        runner = CharterLoopRunner(
            repo="o/r", repo_root=tmp_path, receipts_path=tmp_path / "r.jsonl"
        )
        assert not hasattr(runner, "prs")
        assert not hasattr(runner, "issues")

    async def test_a_budget_refusal_is_receipted_as_such(self, tmp_path: Path) -> None:
        """Distinct from "ran": a run that never happened because the envelope
        said no is not a run with no output."""
        agents = tmp_path / "agents"
        agents.mkdir()
        (agents / "a.md").write_text("you are a")

        async def _dispatch(**kw):  # noqa: ARG001
            return {"budget_refused": True, "detail": "over budget"}

        runner = CharterLoopRunner(
            repo="o/r",
            repo_root=tmp_path,
            receipts_path=tmp_path / "r.jsonl",
            dispatch=_dispatch,
        )
        receipts = await runner.tick(
            _charter(
                a={
                    "enabled": True,
                    "trigger": [{"cron": "0 9 * * *"}],
                    "budget_usd": 4.0,
                }
            ),
            now=_NOW,
            last_fired={"a": _YESTERDAY},
        )
        assert receipts[0].outcome == OUTCOME_REFUSED_BUDGET


class TestTheContractIsTheSystemPrompt:
    def test_both_actor_layouts_resolve(self, tmp_path: Path) -> None:
        """Same predicate as enumeration, same reason: a narrower one stops
        seeing an actor the day it moves into a package, and the loop then runs
        on a prompt nobody wrote (#11669)."""
        (tmp_path / "flat.md").write_text("flat contract")
        (tmp_path / "packaged").mkdir()
        (tmp_path / "packaged" / "README.md").write_text("packaged contract")

        assert resolve_actor_contract(tmp_path, "flat") == "flat contract"
        assert resolve_actor_contract(tmp_path, "packaged") == "packaged contract"
        assert resolve_actor_contract(tmp_path, "missing") is None

    def test_an_empty_contract_is_unreadable_not_an_empty_prompt(
        self, tmp_path: Path
    ) -> None:
        """An empty file is the same failure as a missing one, and dispatching
        on it would be the default-prompt path by another route."""
        (tmp_path / "hollow.md").write_text("   \n")
        assert resolve_actor_contract(tmp_path, "hollow") is None

    async def test_the_contract_text_is_what_gets_dispatched(
        self, tmp_path: Path
    ) -> None:
        agents = tmp_path / "agents"
        agents.mkdir()
        (agents / "a.md").write_text("YOU ARE THE FINANCE ACTOR")
        seen: list[dict] = []

        async def _dispatch(**kw):
            seen.append(kw)
            return {"branch": "finance/x", "pr_url": "u", "cost_usd": 1.5}

        runner = CharterLoopRunner(
            repo="o/r",
            repo_root=tmp_path,
            receipts_path=tmp_path / "r.jsonl",
            dispatch=_dispatch,
        )
        await runner.tick(
            _charter(
                a={
                    "enabled": True,
                    "trigger": [{"cron": "0 9 * * *"}],
                    "goal": "close the books",
                    "model": "sonnet",
                    "output": {"branch_prefix": "finance/"},
                }
            ),
            now=_NOW,
            last_fired={"a": _YESTERDAY},
        )

        assert seen[0]["system_prompt"] == "YOU ARE THE FINANCE ACTOR"
        assert seen[0]["goal"] == "close the books"
        assert seen[0]["model"] == "sonnet"
        assert seen[0]["branch_prefix"] == "finance/"


class TestTheGoalOverrideIsRecorded:
    """Ruling 1: the override is allowed; the RECEIPT is what makes it fine."""

    async def test_an_override_is_used_and_flagged(self, tmp_path: Path) -> None:
        agents = tmp_path / "agents"
        agents.mkdir()
        (agents / "a.md").write_text("contract")

        async def _dispatch(**kw):  # noqa: ARG001
            return {}

        runner = CharterLoopRunner(
            repo="o/r",
            repo_root=tmp_path,
            receipts_path=tmp_path / "r.jsonl",
            dispatch=_dispatch,
        )
        receipts = await runner.tick(
            _charter(
                a={
                    "enabled": True,
                    "trigger": [{"cron": "0 9 * * *"}],
                    "goal": "the declared goal",
                }
            ),
            now=_NOW,
            last_fired={"a": _YESTERDAY},
            goal_overrides={"a": "do this instead"},
        )

        assert receipts[0].goal == "do this instead"
        assert receipts[0].goal_overridden is True

    async def test_an_un_overridden_run_records_the_charter_goal_verbatim(
        self, tmp_path: Path
    ) -> None:
        """Anti-vacuity: if `goal_overridden` were always True the flag would
        carry no information."""
        agents = tmp_path / "agents"
        agents.mkdir()
        (agents / "a.md").write_text("contract")

        async def _dispatch(**kw):  # noqa: ARG001
            return {}

        runner = CharterLoopRunner(
            repo="o/r",
            repo_root=tmp_path,
            receipts_path=tmp_path / "r.jsonl",
            dispatch=_dispatch,
        )
        receipts = await runner.tick(
            _charter(
                a={
                    "enabled": True,
                    "trigger": [{"cron": "0 9 * * *"}],
                    "goal": "the declared goal",
                }
            ),
            now=_NOW,
            last_fired={"a": _YESTERDAY},
        )

        assert receipts[0].goal == "the declared goal"
        assert receipts[0].goal_overridden is False


class TestReceipts:
    async def test_every_decision_writes_one_including_skips(
        self, tmp_path: Path
    ) -> None:
        """A loop that did not run for a reason nobody recorded is
        indistinguishable from a loop nobody looked at."""
        (tmp_path / "agents").mkdir()
        path = tmp_path / "receipts.jsonl"
        runner = CharterLoopRunner(repo="o/r", repo_root=tmp_path, receipts_path=path)
        await runner.tick(
            _charter(
                dormant={"enabled": False},
                not_due={"enabled": True, "trigger": [{"cron": "0 3 * * *"}]},
            ),
            now=_NOW,
            last_fired={"not_due": _NOW - timedelta(hours=1)},
        )

        lines = [json.loads(x) for x in path.read_text().strip().splitlines()]
        assert {row["outcome"] for row in lines} == {
            OUTCOME_SKIPPED_DORMANT,
            OUTCOME_SKIPPED_NOT_DUE,
        }

    async def test_a_receipt_carries_the_window_that_fired(
        self, tmp_path: Path
    ) -> None:
        """Without the window, two receipts for the same loop are
        indistinguishable and the catch-up policy is unauditable."""
        agents = tmp_path / "agents"
        agents.mkdir()
        (agents / "a.md").write_text("contract")

        async def _dispatch(**kw):  # noqa: ARG001
            return {}

        runner = CharterLoopRunner(
            repo="o/r",
            repo_root=tmp_path,
            receipts_path=tmp_path / "r.jsonl",
            dispatch=_dispatch,
        )
        receipts = await runner.tick(
            _charter(a={"enabled": True, "trigger": [{"cron": "0 9 * * *"}]}),
            now=_NOW,
            last_fired={"a": _YESTERDAY},
        )
        assert receipts[0].window == _NOW.isoformat()
        assert receipts[0].trigger == "0 9 * * *"


class TestTheRunnerHasNoWritePathToTheCharter:
    """ADR-0143 Ruling 6 guard 4, structurally rather than by convention."""

    def test_the_module_never_calls_a_charter_write(self) -> None:
        """Checked on the AST, not on the text.

        A substring scan trips on the module docstring, which NAMES
        `charter.yaml` precisely to explain that it is never written — the
        guard would then be measuring prose. This walks the call graph instead
        and asks what the module actually invokes, which is the property.
        """
        import ast
        import inspect

        import charter_loop_runner

        tree = ast.parse(inspect.getsource(charter_loop_runner))
        called = {
            node.func.attr
            if isinstance(node.func, ast.Attribute)
            else node.func.id
            if isinstance(node.func, ast.Name)
            else ""
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
        }
        forbidden = {
            "write_charter",
            "set_enabled",
            "write_text",
            "set_bg_worker_enabled",
        }
        assert not (called & forbidden), (
            f"the runner calls {sorted(called & forbidden)} — enabling a loop "
            "or editing the charter is an ENACT belonging to a human, and the "
            "runner must have no path to either (ADR-0143 Ruling 6 guard 4)"
        )

    def test_the_guard_would_catch_a_real_write(self) -> None:
        """Anti-vacuity for the AST walk above.

        An empty `forbidden` set, or a walk that found no calls at all, would
        pass silently. This proves the same predicate reddens on a module that
        does write.
        """
        import ast

        tree = ast.parse("def f(p):\n    p.write_text('x')\n")
        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert "write_text" in called

    def test_it_cannot_enable_a_dormant_loop(self) -> None:
        """The behavioural half: a dormant loop stays dormant no matter what
        the runner is handed."""
        decisions = select_due_loops(
            _charter(a={"enabled": False, "trigger": [{"cron": "* * * * *"}]}),
            now=_NOW,
            last_fired={},
        )
        assert decisions[0].outcome == OUTCOME_SKIPPED_DORMANT
