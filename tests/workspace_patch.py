"""One ``run_subprocess`` mock across every ``workspace`` slice.

``WorkspaceManager`` became a package in #11547 batch 6. Most tests patch the
single slice whose method they exercise, which is the right shape and fails
loudly when a method moves.

A few flows genuinely cross slices: ``reset_to_main`` and ``merge_main`` live in
``workspace._mainline`` but the fetch they retry happens in
``workspace._remote``. A test that invokes the first and counts calls made by
the second needs ONE mock visible to both — patching a single slice intercepts
half the calls and the assertion then measures the wrong half.

Deliberately not solved by re-exporting ``run_subprocess`` from the package:
each slice binds it at import, so ``patch("workspace.run_subprocess")`` would
replace an attribute nothing reads and pass while testing nothing.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterator

#: Every slice that binds ``run_subprocess``. Kept explicit so adding a slice
#: that binds it without listing it here fails loudly in the guard below.
WORKSPACE_SLICES: tuple[str, ...] = (
    "_manager",
    "_heal",
    "_mainline",
    "_provision",
    "_remote",
)


@contextmanager
def patch_workspace_run_subprocess(**kwargs: Any) -> Iterator[AsyncMock]:
    """Patch ``run_subprocess`` in every slice with a single shared mock."""
    mock = AsyncMock(**kwargs)
    with ExitStack() as stack:
        for slice_name in WORKSPACE_SLICES:
            stack.enter_context(patch(f"workspace.{slice_name}.run_subprocess", mock))
        yield mock
