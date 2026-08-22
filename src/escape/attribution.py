"""Pure mechanical attribution helpers for the escape ledger (#10367).

Mechanical-first, decided in the spec: revert parsing, ``fixes #N`` chains,
regression-pin references, and (future) blame intersection. Each helper is a
pure function over text/paths — no git, no I/O — so the detector and the
caretaker loop compose them against synthetic inputs in unit tests.
Agent-assisted research (Sentry rows) and HITL labelling for low-confidence
rows happen in the loop layer; this module only does the deterministic parse.
"""

from __future__ import annotations

import re

# GitHub's closing keywords (`fixes #123` / `Resolved #123` / …). #11481 folded
# this module's own hand-rolled alternation onto the canonical object so the
# closing-keyword grammar has exactly one definition repo-wide.
from false_close import CLOSE_KEYWORD_RE

# "This reverts commit <sha>." — the body line `git revert` writes. Also the
# `Revert "<subject>"` subject form (captured separately, no sha there).
_REVERTS_COMMIT_RE = re.compile(r"This reverts commit ([0-9a-f]{7,40})")
_REVERT_SUBJECT_RE = re.compile(r'^Revert\s+"')

# A bare `#123` cross-reference (weaker than a closing keyword).
_HASH_REF_RE = re.compile(r"(?<![\w/])#(\d+)\b")

# A hex sha reference of 7-40 chars, word-bounded. A real git sha is effectively
# random hex, so it (almost) always mixes digits AND a-f letters; requiring both
# (checked below) rejects the bogus matches a bare hex class produces — pure
# 7+ digit numbers (issue/line counts) and all-letter English words that happen
# to be hex (``decade``, ``facade``, ``deface``…).
_SHA_REF_RE = re.compile(r"\b([0-9a-f]{7,40})\b")
_HAS_DIGIT_RE = re.compile(r"[0-9]")
_HAS_HEX_LETTER_RE = re.compile(r"[a-f]")


def _looks_like_sha(token: str) -> bool:
    """True when *token* mixes a digit AND an a-f letter — a real-sha shape."""
    return bool(_HAS_DIGIT_RE.search(token) and _HAS_HEX_LETTER_RE.search(token))


# Conventional-commit / free-text hotfix framing.
_HOTFIX_RE = re.compile(r"\bhot[\s-]?fix\b", re.IGNORECASE)

# Repo policy path for a regression pin (P10.6). A NEW file here is the
# mechanical regression-pin signal.
_REGRESSION_DIR = "tests/regressions/"


def parse_reverted_sha(text: str) -> str | None:
    """Return the sha a revert commit reverts, or ``None`` when not a revert."""
    match = _REVERTS_COMMIT_RE.search(text)
    return match.group(1) if match else None


def is_revert(subject: str, body: str) -> bool:
    """True when *subject*/*body* look like a `git revert` commit."""
    return bool(_REVERT_SUBJECT_RE.match(subject.strip())) or (
        parse_reverted_sha(body) is not None
    )


def is_hotfix(subject: str, body: str) -> bool:
    """True when the commit frames itself as a hotfix."""
    return bool(_HOTFIX_RE.search(subject) or _HOTFIX_RE.search(body))


def extract_fixes_refs(text: str) -> list[int]:
    """Return issue/PR numbers named by a GitHub closing keyword, in order."""
    seen: list[int] = []
    for match in CLOSE_KEYWORD_RE.finditer(text):
        num = int(match.group(1))
        if num not in seen:
            seen.append(num)
    return seen


def extract_hash_refs(text: str) -> list[int]:
    """Return every ``#N`` cross-reference in *text*, order-preserving, deduped."""
    seen: list[int] = []
    for match in _HASH_REF_RE.finditer(text):
        num = int(match.group(1))
        if num not in seen:
            seen.append(num)
    return seen


def extract_referenced_shas(text: str, *, exclude: str = "") -> list[str]:
    """Return hex-sha references in *text*, excluding *exclude* (self-ref).

    Only tokens with a real-sha shape (a digit AND an a-f letter) are returned,
    so a pure-digit number or an all-letter hex-looking word is not mistaken for
    an originating merge sha (which would mis-attribute an escape).
    """
    seen: list[str] = []
    for match in _SHA_REF_RE.finditer(text):
        sha = match.group(1)
        if not _looks_like_sha(sha):
            continue
        if exclude and (
            sha == exclude or exclude.startswith(sha) or sha.startswith(exclude)
        ):
            continue
        if sha not in seen:
            seen.append(sha)
    return seen


def regression_pins_added(added_paths: tuple[str, ...]) -> tuple[str, ...]:
    """Return every NEW file in *added_paths* under ``tests/regressions/``."""
    return tuple(p for p in added_paths if p.startswith(_REGRESSION_DIR))


def adds_regression_pin(added_paths: tuple[str, ...]) -> bool:
    """True when this commit adds a NEW file under ``tests/regressions/``."""
    return bool(regression_pins_added(added_paths))
