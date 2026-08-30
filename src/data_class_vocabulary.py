"""The repo data-governance vocabulary — one spelling, importable from pure code.

``public-code`` / ``internal`` / ``regulated-<name>`` is the scale
``repo_store.RepoRecord.data_class`` carries and ``charter.yaml``'s
``articles.assurance`` reuses. There is no second scale (#11748).

It lives here rather than in :mod:`prompt_gate` because two importers need it
and only one of them may touch the world. ``prompt_gate`` writes audit records
(``file_util.append_jsonl``) and observes prompts, so importing it drags I/O
into anything that wants to know whether a string is a valid data class.
:mod:`charter_model` is imported by the decision seam, which is held pure by
``tests/architecture/test_policy_engine_is_pure.py``.

The alternative — each side spelling the regex itself — is two tables over one
vocabulary, which is the defect the charter's own ``actors:`` rule exists to
prevent (ADR-0143 Ruling 6, guard 3) and which shipped anyway as the dual
``Charter`` classes this module's extraction is part of removing.
"""

from __future__ import annotations

# Aliased: the pure seam pins imported SYMBOLS, not whole modules, and a bare
# `compile` binding would shadow the builtin of that name — which the same
# guard refuses, because a shadowed name stops its builtin pin seeing it.
from re import compile as _compile

#: Source available to the vendor; the weakest class.
DATA_CLASS_PUBLIC_CODE = "public-code"
#: The default: internal source, no regulated content.
DATA_CLASS_INTERNAL = "internal"

#: Where classification uncertainty collapses to. Never downward (spec #9734).
FAIL_CLOSED_DATA_CLASS = "regulated-unclassified"

_VALID_CLASS_RE = _compile(r"^(?:public-code|internal|regulated-[a-z0-9][a-z0-9-]*)$")


def is_valid_data_class(raw: str) -> bool:
    """True when *raw* is a well-formed data class string."""
    return bool(_VALID_CLASS_RE.fullmatch(raw.strip()))
