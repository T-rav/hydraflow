"""The `loops:` block and its five guards (#11860, ADR-0145).

`charter.yaml` `schema_version: 1` declares what a repo IS; it cannot declare
what RUNS. Every agent HydraFlow executes is a catalogued Python class, so
adding an agent to a repo means adding a class to the factory. `schema_version:
2` inverts that: the repo declares which actors it has and when they run.

Each guard below is anchored to a defect this repo or the evidence repo has
actually shipped. They are not defensive programming; they are receipts.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from charter import _load_yaml_rejecting_duplicates
from charter_model import (
    Charter,
    CharterError,
    LoopsBlock,
    actors_without_a_loop,
    ambiguous_actors,
    enumerate_actors,
    parse_loops,
    unresolved_actors,
)


class TestBidirectionalBinding:
    """Guard 1. One-way binding is how `standard.yaml` and its README drifted
    until #11751, and the enumeration predicate is part of the CONTRACT — a
    narrow one silently stops seeing an actor that moves into a package."""

    def test_an_actor_that_moved_to_a_package_is_still_enumerated(self) -> None:
        """The mutation test ADR-0145 promised: `x.md` -> `x/README.md`.

        This is the #11669 path-membership class in miniature. A predicate of
        "top-level `*.md` minus README" returns an empty match for the packaged
        layout, and an empty match simply reads as "no such actor" — nothing
        reddens, the loop silently resolves to nothing, and the drift finding
        never fires.
        """
        flat = enumerate_actors(["finance.md", "records.md"])
        packaged = enumerate_actors(["finance.md", "records/README.md"])

        assert flat == ("finance", "records")
        assert packaged == ("finance", "records"), (
            "moving an actor from `records.md` to `records/README.md` made the "
            "enumeration blind to it — the exact shape of #11669"
        )

    def test_documents_and_governance_dirs_are_not_actors(self) -> None:
        """`agents/` holds README/runtime and chamber records beside actors.

        Counting those as actors makes the reverse binding permanently dirty,
        which trains a reader to ignore the finding.
        """
        assert enumerate_actors(
            [
                "finance.md",
                "README.md",
                "runtime.md",
                "council/decisions/0001.md",
                "board/minutes.md",
                "operator/notes.md",
            ]
        ) == ("finance",)

    def test_a_loop_naming_no_actor_is_reported(self) -> None:
        block = parse_loops({"ghost-loop": {"actor": "nobody"}}, present=True)
        assert unresolved_actors(block, ["finance"]) == ("nobody",)

    def test_an_actor_named_by_no_loop_is_a_drift_finding(self) -> None:
        """The non-fatal side, and the asymmetry is deliberate.

        A loop naming a missing actor cannot run. An actor no loop names is a
        repo mid-migration — making that fatal would make migration
        impossible, which is how a guard gets removed rather than satisfied.
        """
        block = parse_loops({"finance-close": {"actor": "finance"}}, present=True)
        assert actors_without_a_loop(block, ["finance", "records"]) == ("records",)
        assert unresolved_actors(block, ["finance", "records"]) == ()

    def test_two_files_for_one_actor_are_reported(self) -> None:
        """`agents/x.md` AND `agents/x/README.md` is the two-tables defect at
        file granularity (ADR-0145)."""
        assert ambiguous_actors(["x.md", "x/README.md", "y.md"]) == ("x",)
        assert ambiguous_actors(["x.md", "y/README.md"]) == ()

    def test_many_loops_may_share_one_actor(self) -> None:
        """The D1 fix. The evidence repo runs `records` and `records-quarterly`
        over one contract, and its runtime already infers that by trimming a
        name suffix — a predicate over names, which is what this repo keeps
        getting wrong."""
        block = parse_loops(
            {
                "records-docket": {"actor": "records"},
                "records-quarterly": {"actor": "records"},
            },
            present=True,
        )
        assert block.actors_named() == ("records",)
        assert unresolved_actors(block, ["records"]) == ()


class TestMisparseIsLoud:
    """Guard 2. `charter.py` already draws this line one level up: `load_charter`
    returns None only for a repo with NO charter."""

    @pytest.mark.parametrize(
        "raw",
        [["finance"], "finance", 42],
        ids=["list", "scalar", "int"],
    )
    def test_an_unparseable_loops_block_raises(self, raw: object) -> None:
        with pytest.raises(CharterError, match="must be a mapping keyed by LOOP"):
            parse_loops(raw, present=True)

    def test_a_loop_body_that_is_not_a_mapping_raises(self) -> None:
        with pytest.raises(CharterError, match="loops.x` must be a mapping"):
            parse_loops({"x": ["not", "a", "mapping"]}, present=True)

    def test_a_non_bool_enabled_raises(self) -> None:
        """Dormancy is a VALUE, not a second list — so it must be a real bool."""
        with pytest.raises(CharterError, match="must be true or false"):
            parse_loops({"x": {"enabled": "yes"}}, present=True)


class TestEmptyIsNotAbsent:
    """Guard 3. The caretaker skips an unmigrated repo and must NOT skip one
    that declared nothing runs."""

    def test_an_empty_loops_block_declares_nothing_runs(self) -> None:
        block = parse_loops(None, present=True)
        assert block.present is True
        assert block.loops == ()

    def test_a_missing_loops_block_is_absent(self) -> None:
        block = parse_loops(None, present=False)
        assert block.present is False

    def test_the_two_are_distinguishable_on_a_loaded_charter(self) -> None:
        """Through the real `from_dict`, because that is where the key check
        lives and a model-level test would not see it."""
        assert Charter.from_dict({"schema_version": 1}).loops.present is False
        assert Charter.from_dict({"loops": {}}).loops.present is True

    def test_a_v1_charter_loads_unchanged(self) -> None:
        """Migration is additive; every repo today has no `loops:` key."""
        charter = Charter.from_dict({"schema_version": 1, "actors": "agents/"})
        assert charter.schema_version == 1
        assert charter.loops == LoopsBlock(present=False)


class TestDuplicateKeysAreAnError:
    """Guard 4. `yaml.safe_load` keeps the LAST duplicate, silently."""

    def test_two_entries_for_one_loop_raise(self) -> None:
        text = (
            "loops:\n"
            "  finance-close:\n"
            "    enabled: true\n"
            "  finance-close:\n"
            "    enabled: false\n"
        )
        with pytest.raises(CharterError, match="duplicate key"):
            _load_yaml_rejecting_duplicates(text)

    def test_the_guard_covers_the_whole_charter_not_only_loops(self) -> None:
        """Scoped to the one place it was noticed is how the next instance goes
        unnoticed. The same hole exists for every block."""
        text = "purpose:\n  statement: a\npurpose:\n  statement: b\n"
        with pytest.raises(CharterError, match="duplicate key"):
            _load_yaml_rejecting_duplicates(text)

    def test_a_charter_without_duplicates_still_loads(self) -> None:
        """Anti-vacuity: a loader that rejected everything would pass above."""
        loaded = _load_yaml_rejecting_duplicates("loops:\n  a:\n    enabled: true\n")
        assert loaded == {"loops": {"a": {"enabled": True}}}


class TestTriggerVocabularyIsBound:
    """Guard 5. An unbound trigger is a loop that silently never fires."""

    def test_an_on_clause_is_rejected_citing_this_adr(self) -> None:
        with pytest.raises(CharterError, match="ADR-0145 Ruling 3") as excinfo:
            parse_loops(
                {"x": {"trigger": [{"on": "records_response_received"}]}}, present=True
            )
        assert "detector" in str(excinfo.value), (
            "the rejection must say WHY it is deferred, or the next author "
            "reads it as an arbitrary restriction and works around it"
        )

    def test_a_cron_clause_is_accepted(self) -> None:
        block = parse_loops({"x": {"trigger": [{"cron": "0 9 * * MON"}]}}, present=True)
        assert block.loops[0].triggers[0].cron == "0 9 * * MON"

    def test_several_clauses_are_a_list_any_of_which_may_fire(self) -> None:
        """The D2 fix: prose triggers like 'weekly · and on each candidate' are
        readable and unschedulable. The schema must hold what the prose says or
        migration is lossy by construction."""
        block = parse_loops(
            {"x": {"trigger": [{"cron": "0 9 * * MON"}, {"cron": "0 9 1 */3 *"}]}},
            present=True,
        )
        assert len(block.loops[0].triggers) == 2

    @pytest.mark.parametrize(
        "cron", ["0 9 * *", "0 9 * * MON extra", ""], ids=["short", "long", "empty"]
    )
    def test_an_unparseable_cron_raises(self, cron: str) -> None:
        with pytest.raises(CharterError):
            parse_loops({"x": {"trigger": [{"cron": cron}]}}, present=True)

    def test_a_scalar_trigger_raises(self) -> None:
        with pytest.raises(CharterError, match="must be a LIST"):
            parse_loops({"x": {"trigger": "weekly"}}, present=True)

    def test_an_unknown_gate_raises(self) -> None:
        """`pr` names what already happens; anything else invents policy."""
        with pytest.raises(CharterError, match="only value at v1.1.0"):
            parse_loops({"x": {"output": {"gate": "auto-merge"}}}, present=True)


class TestTheEnvelopeAndDefaults:
    def test_actor_defaults_to_the_loop_key(self) -> None:
        block = parse_loops({"finance": {}}, present=True)
        assert block.loops[0].actor == "finance"

    def test_a_loop_is_dormant_unless_it_says_otherwise(self) -> None:
        """Silence is declared, not assumed: an undeclared `enabled` must not
        start running work. ADR-0143 Ruling 6 guard 4 makes enabling an ENACT
        that belongs to a human, and a default of True would take that."""
        assert parse_loops({"x": {}}, present=True).loops[0].enabled is False

    def test_the_envelope_round_trips(self) -> None:
        block = parse_loops(
            {
                "x": {
                    "budget_usd": 4.0,
                    "timeout_s": 900,
                    "model": "sonnet",
                    "output": {"branch_prefix": "finance/", "gate": "pr"},
                }
            },
            present=True,
        )
        loop = block.loops[0]
        assert (loop.budget_usd, loop.timeout_s, loop.model) == (4.0, 900, "sonnet")
        assert loop.output.branch_prefix == "finance/"


class TestTheEvidenceRepoFixtureRoundTrips:
    """The loader stress test the scope ruling pulled forward from #11863.

    A v2 rendering of the evidence repo's real `loops.yml`: 15 loops over 11
    actors, including the four whose original triggers are conjunctive
    ("weekly · and on each telemetry candidate"). Migration of a real
    declaration is where schema defects surface, and here they surface days
    earlier than they would in a demo step.

    **Any inexpressible entry fails the build, because then the schema is
    still wrong.** That is the whole point of keeping the fixture at full size
    rather than trimming it to what already parses.
    """

    @staticmethod
    def _fixture() -> Charter:
        import yaml as _yaml

        path = Path(__file__).parent / "fixtures" / "charter" / "gnaa_loops_v2.yaml"
        return Charter.from_dict(_yaml.safe_load(path.read_text("utf-8")))

    def test_every_entry_parses(self) -> None:
        charter = self._fixture()
        assert len(charter.loops.loops) == 15, (
            "an entry from the real declaration did not survive the v2 loader "
            "— the schema cannot hold what the evidence repo actually says"
        )

    def test_many_to_one_survives_migration(self) -> None:
        """11 actors across 15 loops: `finance`, `records`, `legal` and
        `archive` each run more than one. A schema keyed by ACTOR could not
        express this, which is the D1 defect the ADR fixed."""
        charter = self._fixture()
        assert len(charter.loops.actors_named()) == 11
        by_actor: dict[str, int] = {}
        for loop in charter.loops.loops:
            by_actor[loop.actor] = by_actor.get(loop.actor, 0) + 1
        assert sorted(k for k, v in by_actor.items() if v > 1) == [
            "archive",
            "finance",
            "legal",
            "records",
        ]

    def test_dormancy_is_carried_as_a_value(self) -> None:
        """Six of the fifteen are dormant, in the same table as the live ones.

        A separate `dormant:` list would be a second roster admitting both
        contradiction and staleness — the shape `_parse_actors` exists to
        reject, one level down.
        """
        charter = self._fixture()
        dormant = [loop.name for loop in charter.loops.loops if not loop.enabled]
        assert len(dormant) == 6

    def test_the_conjunctive_triggers_are_expressible(self) -> None:
        """The four `on:`-carrying entries render as cron + a documented manual
        trigger, so migration is lossless in the only sense available until a
        detector exists (ADR-0145 Ruling 3)."""
        charter = self._fixture()
        manual = [
            loop.name for loop in charter.loops.loops if "MANUAL TRIGGER" in loop.goal
        ]
        assert len(manual) == 4
        for loop in charter.loops.loops:
            assert loop.triggers, f"{loop.name} has no schedulable clause at all"

    def test_the_fixture_is_bound_both_ways(self) -> None:
        """Guard 1 over a real declaration, not a two-entry toy."""
        charter = self._fixture()
        actors = [f"{name}.md" for name in charter.loops.actors_named()]
        enumerated = enumerate_actors(actors)
        assert unresolved_actors(charter.loops, enumerated) == ()
        assert actors_without_a_loop(charter.loops, enumerated) == ()
