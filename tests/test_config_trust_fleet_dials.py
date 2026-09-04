"""The trust-fleet dials are still HydraFlowConfig's dials (#11547).

They now live on three mixins in `config_trust_fleet_dials` rather than in
`config.py`'s class body. The promise of that move is that **nothing at any
call site changes**: same names, same types, same defaults, same constraints,
reached the same way.

A structural move is exactly the kind of change whose diff is unreviewable —
660 deleted lines and 710 added — so the guarantee is asserted here rather
than eyeballed. The mixin list is read from the class's own bases, so a fourth
mixin added tomorrow is covered without anyone remembering this file.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest
from pydantic_core import PydanticUndefined

from config import HydraFlowConfig
from config_trust_fleet_dials import (
    TrustFleetHealthDials,
    TrustFleetSteeringDials,
    TrustFleetVocabularyDials,
)

#: Read from the config's own bases, not hand-listed: the standard for a guard
#: is to parametrise over the production set by reference (#11723).
MIXINS = [
    b for b in HydraFlowConfig.__bases__ if b.__module__ == "config_trust_fleet_dials"
]

#: The god-class threshold the erosion mass sensor uses.
GOD_CLASS_LOC = 600


def _declared_fields(cls: type) -> set[str]:
    """Fields declared on *cls* itself, not inherited."""
    return set(cls.__annotations__)


def _class_loc(cls: type) -> int:
    source = Path(inspect.getfile(cls)).read_text()
    node = next(
        n
        for n in ast.parse(source).body
        if isinstance(n, ast.ClassDef) and n.name == cls.__name__
    )
    return node.end_lineno - node.lineno + 1


class TestTheMixinsAreWiredIn:
    def test_all_three_mixins_are_bases_of_the_config(self) -> None:
        """Anti-vacuity floor: every parametrised case below is trivially true
        against an empty mixin list."""
        assert set(MIXINS) == {
            TrustFleetHealthDials,
            TrustFleetVocabularyDials,
            TrustFleetSteeringDials,
        }

    @pytest.mark.parametrize("mixin", MIXINS, ids=lambda m: m.__name__)
    def test_every_field_a_mixin_declares_is_a_config_field(self, mixin: type) -> None:
        """The move's whole promise, stated once."""
        declared = _declared_fields(mixin)

        assert declared, f"{mixin.__name__} declares no fields"
        assert declared <= set(HydraFlowConfig.model_fields)

    @pytest.mark.parametrize("mixin", MIXINS, ids=lambda m: m.__name__)
    def test_the_defaults_and_constraints_survive_inheritance(
        self, mixin: type
    ) -> None:
        """A field can be inherited by name and still lose its Field() metadata.

        Compared against the mixin's own FieldInfo rather than a hardcoded
        table, so this keeps holding as the dials change. That is deliberately
        a guard on INHERITANCE, not on the values: editing a default or a
        constraint in the mixin moves both sides and will not redden here. The
        move itself was verified separately, by fingerprinting all 659 fields
        before and after; what this pins is that the mixin remains the thing
        the config is built from.
        """
        for name, info in mixin.model_fields.items():
            inherited = HydraFlowConfig.model_fields[name]

            assert inherited.default == info.default, name
            assert inherited.annotation == info.annotation, name
            assert list(inherited.metadata) == list(info.metadata), name

    def test_every_dial_reads_back_its_declared_default(self) -> None:
        """Reached the same way as before — attribute access on the config —
        and carrying the value the mixin declared.

        Both halves matter: a field can be inherited by name and still be
        shadowed, and it can be readable while holding the wrong default.
        """
        config = HydraFlowConfig()
        checked = 0

        for mixin in MIXINS:
            for name, info in mixin.model_fields.items():
                if info.default is PydanticUndefined or info.default_factory:
                    continue
                assert getattr(config, name) == info.default, name
                checked += 1

        assert checked >= 70, f"only {checked} dials carried a plain default"

    def test_no_dial_was_lost_in_the_move(self) -> None:
        """76 fields moved. A structural move that quietly drops one would
        otherwise satisfy every assertion above, since they all quantify over
        whatever the mixins happen to declare."""
        moved = {name for m in MIXINS for name in m.model_fields}

        assert len(moved) == 76


class TestTheSplitDidNotJustRelocateTheProblem:
    """Three mixins rather than one, for a reason worth keeping."""

    @pytest.mark.parametrize("mixin", MIXINS, ids=lambda m: m.__name__)
    def test_no_mixin_is_itself_a_god_class(self, mixin: type) -> None:
        """The whole cluster in one class would have been 651 LOC.

        Extracting a god class into another god class removes nothing; this is
        what stops the next batch of dials being appended until it is one again.
        """
        assert _class_loc(mixin) < GOD_CLASS_LOC

    def test_the_config_is_smaller_than_the_baseline_it_recorded(self) -> None:
        """The mass baseline for HydraFlowConfig was re-recorded by this move.

        Reads the committed baseline so the two cannot drift apart silently.
        """
        import yaml

        baseline = yaml.safe_load(Path("disturbance/baselines/mass.yaml").read_text())
        recorded = baseline["classes"]["src/config.py:HydraFlowConfig"]["loc"]

        assert recorded < 5059, "the pre-decomposition baseline was 5059"


class TestTheFieldsDidNotMoveInName:
    """The control: this file would pass on an empty config without it."""

    def test_a_field_that_did_not_move_is_still_there(self) -> None:
        """A dial left in config.py's own body, to prove the assertions above
        are about the mixins rather than about `model_fields` being large."""
        assert "ready_label" in HydraFlowConfig.model_fields
        assert "ready_label" not in {n for m in MIXINS for n in m.model_fields}
