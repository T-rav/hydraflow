"""Release-artifact surface of ``FakeGitHub``.

Extracted VERBATIM from ``src/mockworld/fakes/fake_github.py``
(god-class decomposition, Refs #11547) as a mixin. ``FakeGitHub`` inherits it,
so every method here still resolves as an attribute of ``FakeGitHub`` and every
seam that drives the fake through a Port resolves to the same object as before.

The cluster boundary mirrors the real adapter's: this module is the fake's
side of ``pr_manager_artifacts.PRManagerArtifactsMixin``, so the fake and the thing it doubles read alike.

One concern: what the fake records when the pipeline publishes something — the
ADR-0011 tag and release pair (plus the inspectors scenarios assert on) and the
screenshot upload the visual gate calls.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


class FakeGitHubArtifactsMixin:
    """Release-artifact surface of ``FakeGitHub``."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``FakeGitHub.__init__`` or by
    # a sibling mixin. The method declarations are TYPE_CHECKING-only
    # on purpose: a runtime ``...`` body would win over the
    # real implementation whenever this mixin precedes the
    # implementing one in ``FakeGitHub``'s MRO.
    # ------------------------------------------------------------------
    _releases: dict[str, tuple[str, str]]
    _tags: dict[str, str]

    if TYPE_CHECKING:

        def _maybe_rate_limit(self) -> None: ...  # provided by _seeding

    async def upload_screenshot(self, **_kw: Any) -> str:
        self._maybe_rate_limit()
        return ""

    async def create_tag(self, tag: str, *, ref: str) -> bool:
        """Record *tag* -> *ref*; a duplicate tag fails like ``git tag`` does."""
        self._maybe_rate_limit()
        if tag in self._tags:
            return False
        self._tags[tag] = ref
        return True

    async def create_release(self, tag: str, title: str, body: str) -> bool:
        """Record the GitHub Release for *tag*."""
        self._maybe_rate_limit()
        self._releases[tag] = (title, body)
        return True

    @property
    def tags(self) -> dict[str, str]:
        """``{tag: ref}`` recorded by :meth:`create_tag` (a copy)."""
        return dict(self._tags)

    @property
    def releases(self) -> dict[str, tuple[str, str]]:
        """``{tag: (title, body)}`` recorded by :meth:`create_release` (a copy)."""
        return dict(self._releases)
