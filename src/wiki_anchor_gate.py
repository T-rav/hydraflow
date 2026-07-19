"""Repo-specificity gate for wiki synthesis entries (#9954).

The wiki issue-synthesis pipeline (:meth:`WikiCompiler.compile_topic_tracked`)
was minting generic coding truisms — "Use ``is None`` for optional
sentinels", "Delete code blocks bottom-to-top" — as durable
repo-knowledge entries. Those platitudes dilute the wiki context injected
into agent prompts (``max_repo_wiki_chars`` truncates, so platitudes crowd
out the real gotchas), inflate synthesis/compile cost, and drove the
maintenance-PR treadmill.

An entry earns its place only if it references something *specific to this
repository*. This module is the cheap, deterministic heuristic:

``has_repo_anchor(text)`` is ``True`` when *text* mentions at least one of

- a ``.py`` module path (``src/repo_wiki.py`` or ``wiki_compiler.py``),
- an ADR number (``ADR-0042`` / ``adr 53``),
- a HydraFlow class name by convention — a CamelCase word ending in a
  loop/port/runner/store/… suffix, or a ``Fake*``/``Mock*`` test double,
- a known ``HydraFlowConfig`` field (``rc_cadence_hours``,
  ``max_repo_wiki_chars``) when a config-field vocabulary is supplied.

The config-field vocabulary is derived at call time from
``HydraFlowConfig.model_fields`` so the gate tracks the real config surface
without a hand-maintained list. The heuristic is side-effect-free and
pure (given ``config_fields``) so it is trivially unit-testable and cheap
enough to run on every synthesized entry.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

# --- structural anchors (no external vocabulary needed) --------------------

# A ``.py`` module reference, slashed or bare (``src/foo/bar.py`` or
# ``bar.py``). The ``.py`` suffix is required so ordinary dotted prose
# ("e.g.", "3.11") never matches; a word char must precede ``.py`` so a
# bare ".py" does not match either.
_PY_PATH_RE = re.compile(r"\b[\w./-]*\w\.py\b")

# ADR reference: ``ADR-0042`` / ``ADR 42`` / ``adr-0053``.
_ADR_RE = re.compile(r"\badr[-\s]?\d{1,4}\b", re.IGNORECASE)

# HydraFlow class names by convention: a CamelCase word ending in one of the
# load-bearing infra suffixes (see docs/arch/generated/loops.md + ports.md),
# or a ``Fake*`` / ``Mock*`` test double. A prefix segment is required (the
# suffix cannot stand alone) so a bare English word like "Store" or "Queue"
# is not mistaken for a class name.
_CLASS_SUFFIXES = (
    "Loop",
    "Port",
    "Runner",
    "Store",
    "Manager",
    "Coordinator",
    "Gate",
    "Detector",
    "Queue",
    "Watcher",
    "Reconciler",
    "Registry",
    "Tracker",
    "Auditor",
    "Sweeper",
    "Sensor",
    "Monitor",
    "Dampener",
    "Proposer",
    "Scorecard",
)
_CLASS_RE = re.compile(
    r"\b(?:[A-Z][a-zA-Z0-9]*(?:" + "|".join(_CLASS_SUFFIXES) + r")"
    r"|(?:Fake|Mock)[A-Z][a-zA-Z0-9]+)\b"
)

# Snake_case token extractor for config-field matching.
_SNAKE_TOKEN_RE = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+")


def _distinctive_config_fields(field_names: Iterable[str]) -> frozenset[str]:
    """Keep only multi-token (snake_case) field names.

    Single-word fields like ``model`` / ``repo`` appear in ordinary prose and
    would false-positive the gate; requiring an underscore restricts the
    vocabulary to distinctive identifiers.
    """
    return frozenset(f for f in field_names if "_" in f)


def config_field_vocabulary() -> frozenset[str]:
    """Distinctive ``HydraFlowConfig`` field names, resolved at call time.

    ``config`` is imported lazily so this module stays import-cheap and can
    be unit-tested without constructing a config instance.
    """
    from config import HydraFlowConfig  # noqa: PLC0415

    return _distinctive_config_fields(HydraFlowConfig.model_fields)


def has_repo_anchor(
    text: str,
    *,
    config_fields: Iterable[str] | None = None,
) -> bool:
    """Return ``True`` when *text* references something repo-specific.

    Deterministic and side-effect-free. Structural anchors (``.py`` paths,
    ADR numbers, HydraFlow class names) need no vocabulary. Pass
    *config_fields* (e.g. :func:`config_field_vocabulary`) to also anchor on
    a known config-field mention — omit it for structural-only checks.
    """
    if not text:
        return False
    if _PY_PATH_RE.search(text) or _ADR_RE.search(text) or _CLASS_RE.search(text):
        return True
    if config_fields is not None:
        vocab = (
            config_fields
            if isinstance(config_fields, frozenset | set)
            else frozenset(config_fields)
        )
        if vocab:
            for token in _SNAKE_TOKEN_RE.findall(text):
                if token in vocab:
                    return True
    return False
