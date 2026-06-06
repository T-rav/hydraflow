"""Canonical type aliases for FastAPI route parameters and API DTOs.

Import shared parameter types from here — never duplicate ``Annotated[...]``
definitions in individual route modules.
"""

from __future__ import annotations

from typing import Annotated, TypeAlias

from fastapi import Query

from models import (
    ControlStatusConfig,
    ControlStatusResponse,
)

# Reserved sentinel: a non-slug-legal token that can never collide with a real
# ``owner/repo`` slug. ``repo=__all__`` selects the cross-repo aggregate.
REPO_ALL = "__all__"

RepoSlugParam: TypeAlias = Annotated[
    str | None,
    Query(description="Repo slug to scope the request"),
]


__all__ = [
    "REPO_ALL",
    "ControlStatusConfig",
    "ControlStatusResponse",
    "RepoSlugParam",
]
