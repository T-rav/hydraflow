"""Barren-compile ledger — remember the syntheses the anchor gate rejected (#11888).

The #11373 fingerprint gate already stops an UNCHANGED topic from re-paying its
synthesis spawn. It keys on the topic's *input* content, and that is the half of
the problem it can see. The other half: a topic's content churns for reasons that
have nothing to do with whether synthesis can make progress — one ingested entry,
the lint pass marking six entries stale, a landed maintenance PR. Each of those
changes the fingerprint, re-opens the gate, and buys another full synthesis over
substantially the same inputs.

Measured live on the running factory, 2026-08-30/31: ``patterns`` compiled on
seven separate ticks and the anchor gate (#9954) dropped the SAME twelve titles
every time — 552 drops, ``entries_compiled: 0`` on all 27 maintenance runs in the
log, against 87 model timeouts at 300s apiece. The loop could not tell "the topic
changed" from "the outcome could change", so it re-bought a rejection it had
already paid for.

This ledger keys on the OUTPUT instead, which is the thing that actually has to
change for the spend to be worth it. A compile that writes nothing AND whose every
rejection was already on file has demonstrably bought nothing; the topic is marked
barren and skipped until *cooldown_hours* elapses. Any write, or any rejection
never seen before, means the output is still moving and clears the mark.

Fail-open, exactly like ``wiki_compile_state``: a missing or corrupt file means
"compile everything once". This gate can only ever save spawns, never suppress a
topic that is genuinely making progress.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("hydraflow.repo_wiki")

_WHITESPACE = re.compile(r"\s+")


def synthesis_digest(title: str, content: str) -> str:
    """Stable identity for one synthesized entry, insensitive to cosmetic drift.

    A model re-asked the same question re-emits the same claim with different
    wrapping — a stray blank line, different capitalisation. Those are one
    rejection, not two, or the ledger never accumulates a repeat and the gate
    below never fires.
    """
    normalized = _WHITESPACE.sub(" ", f"{title}\n{content}").strip().casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class WikiSynthesisLedger:
    """Rejected-synthesis memory and the barren mark it supports."""

    def __init__(self, path: Path, *, cooldown_hours: float) -> None:
        self._path = path
        self._cooldown_hours = cooldown_hours
        self._dirty = False
        #: ``slug:topic`` -> {"rejected": [digest, ...], "barren_at": iso|None}
        self._state: dict[str, dict[str, Any]] = {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(raw, dict):
            return
        for key, value in raw.items():
            if not isinstance(value, dict):
                continue
            rejected = value.get("rejected")
            barren_at = value.get("barren_at")
            self._state[str(key)] = {
                "rejected": [str(d) for d in rejected]
                if isinstance(rejected, list)
                else [],
                "barren_at": barren_at if isinstance(barren_at, str) else None,
            }

    @staticmethod
    def _key(slug: str, topic: str) -> str:
        return f"{slug}:{topic}"

    def should_compile(self, slug: str, topic: str, *, now: datetime) -> bool:
        """False only while *topic* is marked barren and the cooldown is unspent."""
        entry = self._state.get(self._key(slug, topic))
        if entry is None:
            return True
        barren_at = entry.get("barren_at")
        if not barren_at:
            return True
        try:
            marked = datetime.fromisoformat(barren_at)
        except ValueError:
            return True  # unparseable mark is no mark — fail open
        if marked.tzinfo is None:
            marked = marked.replace(tzinfo=UTC)
        elapsed_hours = (now - marked).total_seconds() / 3600.0
        return elapsed_hours >= self._cooldown_hours

    def record_compile(
        self,
        slug: str,
        topic: str,
        *,
        rejected: list[str],
        wrote: int,
        now: datetime | None = None,
    ) -> bool:
        """Fold one compile's outcome in. Returns True when it marked *topic* barren.

        ``rejected`` is the digest of every synthesis the anchor gate dropped;
        ``wrote`` is how many entries actually landed. An empty *rejected* is NOT
        barren: that is the model-failure path (a timeout returns no entries at
        all), which the circuit breaker in ``wiki_compiler._model_io`` owns. Two
        gates on one signal would each read the other's suppression as success.
        """
        now = now or datetime.now(UTC)
        key = self._key(slug, topic)
        entry = self._state.setdefault(key, {"rejected": [], "barren_at": None})
        known = set(entry["rejected"])
        fresh = [d for d in rejected if d not in known]
        if fresh:
            entry["rejected"] = [*entry["rejected"], *fresh]
            self._dirty = True

        # A write, a brand-new rejection, or no rejection at all: the output is
        # still moving (or never arrived). Clear any standing mark.
        if wrote > 0 or fresh or not rejected:
            if entry["barren_at"] is not None:
                entry["barren_at"] = None
                self._dirty = True
            return False

        # Nothing written, and every rejection was already on file.
        if entry["barren_at"] is None:
            entry["barren_at"] = now.isoformat()
            self._dirty = True
            logger.warning(
                "Wiki synthesis for %s/%s is barren — it wrote nothing and every "
                "one of its %d rejected entries was already on file. Skipping its "
                "spawn for %.0fh. The inputs keep changing but the output does "
                "not, so re-compiling re-buys a rejection already paid for.",
                slug,
                topic,
                len(rejected),
                self._cooldown_hours,
            )
        return True

    def save(self) -> None:
        """Best-effort persist. No-op when nothing changed — an idle tick must
        not touch disk (the wiki heal contract asserts a byte-clean tree)."""
        if not self._dirty:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._state, indent=2, sort_keys=True), encoding="utf-8"
            )
        except OSError:
            logger.warning(
                "wiki synthesis-ledger save failed (%s) — next tick recompiles",
                self._path,
                exc_info=True,
            )
