"""Shared type aliases for route parameters."""

from __future__ import annotations

from typing import Annotated

from fastapi import Query

RepoSlugParam = Annotated[
    str | None,
    Query(description="Repo slug to scope the request"),
]
