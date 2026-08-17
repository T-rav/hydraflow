"""Fingerprint gate for wiki topic compilation (#11373).

The RepoWikiLoop used to spawn an LLM synthesis for EVERY topic with 5+
active entries on EVERY tick, changed or not. A topic that never compiles
below the threshold (e.g. one held open by quarantined/malformed entries)
re-paid the spawn forever — measured live at 23% of the entire factory's
token burn (1.66M tokens / 132 spawns in 12h).

This module gates the spawn on a content fingerprint: a topic only
compiles when its active content actually changed since the last
successful compile. Pure I/O-light helpers; the state file lives under
the gitignored data path (the wiki tree itself is an ephemeral worktree,
so mtimes are useless and the state must persist outside it).

Fail-open by design: a missing/corrupt state file means "compile
everything once" — the gate can only ever save spawns, never suppress a
genuinely-changed topic.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

logger = logging.getLogger("hydraflow.repo_wiki")


def topic_fingerprint(chunks: list[bytes | str]) -> str:
    """Stable content hash over a topic's active content.

    Callers pass file bytes (tracked layout) or serialized entries
    (legacy layout); ordering is normalized here so directory iteration
    order can't produce spurious "changes".
    """
    digest = hashlib.sha256()
    normalized = sorted(
        chunk.encode("utf-8") if isinstance(chunk, str) else chunk for chunk in chunks
    )
    for chunk in normalized:
        digest.update(hashlib.sha256(chunk).digest())
    return digest.hexdigest()


class WikiCompileState:
    """Last-compiled fingerprint per ``slug:topic:layout`` key."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._dirty = False
        self._state: dict[str, str] = {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._state = {
                    str(k): str(v) for k, v in raw.items() if isinstance(v, str)
                }
        except (OSError, ValueError):
            self._state = {}

    def should_compile(self, key: str, fingerprint: str) -> bool:
        """True when *key*'s content changed since its last recorded compile."""
        return self._state.get(key) != fingerprint

    def record(self, key: str, fingerprint: str) -> None:
        """Record a successful compile of *key* at *fingerprint*."""
        if self._state.get(key) != fingerprint:
            self._state[key] = fingerprint
            self._dirty = True

    def save(self) -> None:
        """Best-effort persist — a failed save just means a re-compile later.

        No-op when nothing was recorded this cycle: an idle tick must not
        touch disk (the wiki heal contract asserts a byte-clean tree).
        """
        if not self._dirty:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._state, indent=2, sort_keys=True), encoding="utf-8"
            )
        except OSError:
            logger.warning(
                "wiki compile-state save failed (%s) — next tick recompiles",
                self._path,
                exc_info=True,
            )
