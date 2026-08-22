"""Guard (#11629): a mixin's seam declarations must not exist at runtime.

The house god-class recipe — "extract a cohesive cluster into a mixin module
and have the host class inherit it" — is used by ``src/state/`` (55 mixins on
``StateTracker``), ``src/pr_manager_promotion.py`` and
``src/review_phase/_visual_gate.py``, and the #11547 erosion roster keeps
pointing new decompositions at it. A mixin has to name collaborators it does
not own, and the tempting spelling is a runtime stub::

    class SeamMixin:
        def _remove_label(self, ...) -> None: ...  # provided by the host

With ONE mixin that is safe — the host's real definition always precedes the
mixin in ``__mro__``. With two or more it is not: attribute lookup stops at the
FIRST class in the MRO carrying the name, so a stub in an earlier mixin wins
over a *sibling* mixin's real implementation, and a ``...`` body returns
``None`` instead of raising. That is silent: ruff is clean, pyright is clean
(the stub type-checks fine), the module imports fine, and the call site simply
gets ``None`` back and fails somewhere else entirely — or not at all. It bit
PR #11628 twice; one instance was caught only because a unit test happened to
cover that path.

Two tests, from the outside in:

* :func:`test_no_seam_stub_shadows_a_sibling_implementation` — the bug itself.
  Reconstructs each class's real C3 linearization from the on-disk AST and
  fails on any name whose winner is a stub while a later MRO entry implements
  it. This is the check PR #11628 ran ad hoc against ``PRManager`` and
  ``ReviewPhase``, generalised to the whole tree.
* :func:`test_inherited_classes_declare_method_seams_under_type_checking` —
  the structural rule that keeps the first test from ever having something to
  find. Typing-only declarations are the stronger fix of the two the issue
  proposed (``if TYPE_CHECKING:`` vs. a ``raise NotImplementedError`` body):
  a non-existent attribute cannot shadow anything, whereas a raising stub
  still wins the MRO and merely converts a silent wrong answer into a crash.

No ratchet and no grandfather list: every pre-existing site was migrated, so
both scans sit at zero and stay there.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.architecture.mixin_seam_scan import (
    collect_classes,
    scan_runtime_method_seams,
    scan_shadowed_seams,
)

if TYPE_CHECKING:
    from pathlib import Path

# Decomposition hosts whose mixin bases this guard exists to protect. If a
# rename drops one of these the guard could go quietly vacuous, so the scan is
# asserted to still see them.
_KNOWN_DECOMPOSITION_HOSTS = {
    "state:StateTracker",
    "pr_manager:PRManager",
    "review_phase._phase:ReviewPhase",
}


def test_no_seam_stub_shadows_a_sibling_implementation(real_repo_root: Path) -> None:
    """No class in ``src/`` resolves a method to a stub that a sibling implements."""
    offenders = scan_shadowed_seams(real_repo_root)

    assert not offenders, (
        "mixin seam stub(s) win the MRO over a real sibling implementation — the "
        "call site silently gets `None` back (#11629). Move the declaration under "
        "`if TYPE_CHECKING:` so no runtime attribute is created:\n  "
        + "\n  ".join(o.describe() for o in offenders)
    )


def test_inherited_classes_declare_method_seams_under_type_checking(
    real_repo_root: Path,
) -> None:
    """No inherited ``src/`` class carries a runtime ``...`` method body."""
    offenders = scan_runtime_method_seams(real_repo_root)

    assert not offenders, (
        "class(es) that another `src/` class inherits declare a method seam as a "
        "RUNTIME `...` stub. That is a real class attribute and will shadow a "
        "sibling mixin's implementation as soon as the host gains a second mixin "
        "(#11629). Attribute annotations (`_config: HydraFlowConfig`) stay safe "
        "unguarded; method stubs must move under `if TYPE_CHECKING:`. `Protocol` "
        "and `abc.ABC` subclasses are exempt and need no change:\n  "
        + "\n  ".join(o.describe() for o in offenders)
    )


def test_guard_still_sees_the_live_decomposition_hosts(real_repo_root: Path) -> None:
    """Sanity: a rename must not make the two scans silently vacuous."""
    missing = sorted(_KNOWN_DECOMPOSITION_HOSTS - set(collect_classes(real_repo_root)))

    assert not missing, (
        "the mixin-seam scan no longer finds these god-class decomposition hosts, "
        "so it may be checking nothing. Re-point `_KNOWN_DECOMPOSITION_HOSTS` at "
        f"their new module:class keys: {missing}"
    )
