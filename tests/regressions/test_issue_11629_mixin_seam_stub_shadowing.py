"""Regression: a runtime ``...`` seam stub in one mixin silently shadows a
sibling mixin's real implementation via the MRO (#11629).

The house god-class recipe is "extract a cohesive cluster into a mixin module
and have the parent inherit it" (``pr_manager_promotion.py``,
``review_phase/_visual_gate.py``, the whole of ``src/state/``). Those mixins
declared the collaborators they need as **runtime** stubs::

    class PromotionMixin:
        async def _run_gh(self, *cmd: str) -> str: ...  # provided by the host

That is safe with exactly ONE mixin, because the host's real definition always
precedes the mixin in the MRO. It stops being safe the moment the host inherits
two or more mixins and one of them declares a seam that a *sibling* mixin
implements: ``type.__getattribute__`` walks ``__mro__`` left to right and stops
at the FIRST class carrying the name, so the stub wins. A ``...`` body returns
``None`` and does nothing, so the call site gets ``None`` back and fails
somewhere else entirely — or does not fail at all.

The fix is that a *method* seam declaration must never exist at runtime: guard
it with ``if TYPE_CHECKING:`` so pyright still sees the signature but no class
attribute is ever created, and a non-existent attribute cannot shadow anything.
Attribute *annotations* (``_config: HydraFlowConfig``) stay safe unguarded —
a bare annotation creates no class attribute.

The first two tests pin the language mechanic itself (trap, then cure); the
last two pin that :mod:`tests.architecture.mixin_seam_scan` — the guard that
makes the trap unrepeatable — actually distinguishes the two shapes.
"""

from __future__ import annotations

from textwrap import dedent
from typing import TYPE_CHECKING

from tests.architecture.mixin_seam_scan import scan_shadowed_seams

if TYPE_CHECKING:
    from pathlib import Path


# --------------------------------------------------------------------------
# The language mechanic: what the trap does, and what the cure does.
# --------------------------------------------------------------------------


class _SeamsAsRuntimeStubs:
    """The UNSAFE shape — a runtime ``...`` body is a real class attribute."""

    def compute(self) -> str: ...  # "provided by a sibling"


class _SeamsUnderTypeChecking:
    """The SAFE shape — no runtime attribute is created for ``compute``."""

    if TYPE_CHECKING:

        def compute(self) -> str: ...


class _ComputeImpl:
    """The sibling mixin that actually implements the seam."""

    def compute(self) -> str:
        return "real"


class _UnsafeHost(_SeamsAsRuntimeStubs, _ComputeImpl):
    """MRO: host, stub-declaring mixin, implementing mixin — the stub wins."""


class _SafeHost(_SeamsUnderTypeChecking, _ComputeImpl):
    """Same MRO order, but the seam declaration does not exist at runtime."""


def test_runtime_seam_stub_shadows_a_sibling_mixins_implementation() -> None:
    """The trap: the ``...`` stub wins the MRO and silently returns ``None``."""
    assert _UnsafeHost().compute() is None


def test_type_checking_guarded_seam_lets_the_sibling_implementation_win() -> None:
    """The cure: no runtime attribute, so the sibling's real body resolves."""
    assert _SafeHost().compute() == "real"


# --------------------------------------------------------------------------
# The guard: it must tell those two shapes apart on an on-disk source tree.
# --------------------------------------------------------------------------

_SIBLING_IMPL_MODULE = """
    class ComputeMixin:
        def compute(self) -> str:
            return "real"
"""

_UNSAFE_SEAM_MODULE = """
    class SeamMixin:
        def compute(self) -> str: ...
"""

_SAFE_SEAM_MODULE = """
    from typing import TYPE_CHECKING

    class SeamMixin:
        if TYPE_CHECKING:
            def compute(self) -> str: ...
"""

_HOST_MODULE = """
    from compute_mixin import ComputeMixin
    from seam_mixin import SeamMixin

    class Host(SeamMixin, ComputeMixin):
        pass
"""


def _tree(tmp_path: Path, seam_module: str) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    (src / "compute_mixin.py").write_text(dedent(_SIBLING_IMPL_MODULE))
    (src / "seam_mixin.py").write_text(dedent(seam_module))
    (src / "host.py").write_text(dedent(_HOST_MODULE))
    return tmp_path


def test_guard_flags_a_runtime_seam_stub_that_shadows_a_sibling(
    tmp_path: Path,
) -> None:
    """The unsafe two-mixin shape is reported as an offender."""
    offenders = scan_shadowed_seams(_tree(tmp_path, _UNSAFE_SEAM_MODULE))

    assert [o.method for o in offenders] == ["compute"]


def test_guard_accepts_a_type_checking_guarded_seam(tmp_path: Path) -> None:
    """The cured shape produces no offenders — the guard is not shape-blind."""
    assert scan_shadowed_seams(_tree(tmp_path, _SAFE_SEAM_MODULE)) == []
