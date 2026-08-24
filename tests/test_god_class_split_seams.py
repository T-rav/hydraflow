"""Seam-block generation in ``scripts/god_class_split.py``.

The tool is the house recipe for the standing god-class roster (#11547): it
slices methods into mixin modules and generates each mixin's collaborator-seam
block. A seam it fails to emit is a name the mixin never declares, which pyright
reports as ``Cannot access attribute "_x" for class "FooMixin*"`` — loud, but
only after a full ``make quality``, which is an expensive way to learn it.

These pin the two shapes a seam can take, so the generator cannot quietly stop
emitting one.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from god_class_split import (  # noqa: E402
    _seam_block,
    _self_attrs,
    _summary_sentence,
)

_SOURCE = """
class Host:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._suggest_memory = MemorySuggester(config)

    def owned(self) -> None:
        self._helper()
        self._suggest_memory("x")
        print(self._config)

    def _helper(self) -> None: ...
"""


def _host() -> ast.ClassDef:
    tree = ast.parse(_SOURCE)
    return next(n for n in tree.body if isinstance(n, ast.ClassDef))


def _block_for(owned_name: str) -> str:
    cls = _host()
    methods = {
        n.name: n
        for n in cls.body
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    called, read = _self_attrs(methods[owned_name])
    return _seam_block(
        cls_name="Host",
        owned={owned_name},
        used_methods=called,
        used_attrs=read,
        all_methods=methods,
        provider_of={"_helper": "_other"},
        attr_types={"_config": "Config"},
    )


def test_callable_collaborator_attribute_gets_a_seam() -> None:
    """``self._x(...)`` where ``_x`` is an ATTRIBUTE, not a sibling method.

    It reads as a call, so ``_self_attrs`` files it under *called*; it is not a
    method of the class, so it is not a sibling seam either. Before the union in
    ``_seam_block`` it fell out of both lists and no seam was emitted at all —
    the ``_suggest_memory`` gap in two ``pr_unsticker`` slices (#11547 batch 7).
    """
    block = _block_for("owned")
    assert "_suggest_memory" in block, (
        "callable collaborator attribute got no seam declaration:\n" + block
    )


def test_sibling_method_seam_stays_type_checking_only() -> None:
    """A real sibling method keeps its ``if TYPE_CHECKING:`` guard (#11629).

    A runtime ``...`` body is a class attribute and wins the MRO over the
    sibling that really implements it, silently returning ``None``.
    """
    block = _block_for("owned")
    guard = block.index("if TYPE_CHECKING:")
    assert block.index("_helper", guard) > guard, (
        "sibling method seam emitted outside the TYPE_CHECKING guard:\n" + block
    )
    # A plain attribute is safe unguarded and must stay above the guard.
    assert block.index("_config") < guard, (
        "attribute annotation was pushed under TYPE_CHECKING:\n" + block
    )


def test_class_summary_is_a_whole_sentence() -> None:
    """The generated class docstring must not stop mid-clause.

    A module docstring is prose wrapped at the source width, so its first
    PHYSICAL line usually ends mid-clause. Publishing that as the mixin's own
    summary shipped fragments like "what an epic does when one of its issues"
    into three ``src/epic/`` classes (#11547 batch 7).
    """
    doc = (
        "The child-lifecycle callbacks: what an epic does when one of its\n"
        "issues moves.\n\nFive entry points driven by the label state machine."
    )
    assert _summary_sentence(doc) == (
        "The child-lifecycle callbacks: what an epic does when one of its issues moves."
    )


def test_class_summary_without_a_sentence_end_keeps_the_paragraph() -> None:
    """No period to cut at means keep the paragraph, never a bare fragment."""
    assert _summary_sentence("A summary with no full stop") == (
        "A summary with no full stop"
    )
