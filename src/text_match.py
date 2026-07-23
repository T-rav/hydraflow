"""Shared whole-word keyword matcher for the insight classifiers (#9659).

Both :func:`review_insights.extract_categories` (prose review summaries) and
:func:`harness_insights.extract_subcategories` (failure-log details) classify
free text by scanning it for category keywords. They previously carried
near-identical private ``_keyword_matches`` helpers; this module is the single
place that owns the matching semantics so the two classifiers can never drift
apart (#9566 aligned them, #9659 consolidated them).

Anchoring policy (explicit, in one place)
-----------------------------------------
A keyword matches only on **full word boundaries** — a leading ``\\b`` and a
trailing ``\\b`` around the escaped keyword. Both the prose and failure-log
classifiers use this identical anchoring:

* the 3-char ``"test"`` matches ``"test"`` but **not** ``"tests"`` or
  ``"latest"``;
* broad terms (``"type"``, ``"format"``) never match inside a larger identifier
  (``"prototype"``, ``"typescript"``, ``"information"``);
* non-word characters *inside* a keyword (``"try/except"``) are matched
  literally, and the trailing boundary applies to the keyword's last word
  character so ``"try/except"`` does not match inside ``"try/exception"``.

The matcher is case-sensitive by design: callers lowercase both the keyword and
the text once, up front, and reuse the lowercased text across every keyword.
"""

from __future__ import annotations

import re

__all__ = ["keyword_matches"]


def keyword_matches(keyword: str, text: str) -> bool:
    """Return ``True`` when *keyword* occurs in *text* on whole-word boundaries.

    Uses ``\\b`` boundaries around the escaped keyword so a short token matches
    only as a standalone word/phrase, never inside a larger identifier. See the
    module docstring for the full anchoring policy.

    Both arguments are matched as-is; for case-insensitive matching callers pass
    already-lowercased strings.
    """
    pattern = r"\b" + re.escape(keyword) + r"\b"
    return re.search(pattern, text) is not None
