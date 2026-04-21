"""Minimal fakes for builders that touch external deps during prompt rendering.

Each fake is the smallest object that satisfies the attribute/method surface the
builder actually calls. Do not add behavior here — if a builder reaches into
the fake in a way not covered, extend the fake with a named variant instead of
making the default smarter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class _EmptyRepoWikiStore:
    def get_entries(self) -> list[Any]:
        return []

    def query(self, *_args: Any, **_kwargs: Any) -> list[Any]:
        return []


_MINIMAL_MANIFEST = [
    "src/agent.py",
    "src/reviewer.py",
    "src/triage.py",
]


_REGISTRY: dict[tuple[str, str], Any] = {
    ("repo_wiki_store", "empty"): _EmptyRepoWikiStore(),
    ("manifest", "minimal"): _MINIMAL_MANIFEST,
}


def get_fake(kind: str, shape: str) -> Any:
    key = (kind, shape)
    if key not in _REGISTRY:
        raise KeyError(f"no fake registered for ({kind!r}, {shape!r}); extend fakes.py")
    return _REGISTRY[key]
