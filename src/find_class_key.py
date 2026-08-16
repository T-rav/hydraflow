"""Class-key fold layer for pattern-shaped find-issues (#11292).

Board-growth analysis found three defect FAMILIES each spawning 3-4 sibling
``hydraflow-find`` issues for ONE underlying defect class (branch-name
parsers missing the ``agent/auto-agent-<N>`` namespace: #11188/#11275/#11281;
non-self-retiring ADR pins: #11192/#11193/#11195). Each sibling was
individually correct, but per-site filing triples triage load and invites
parallel-build collisions (the documented dup-issue collision class).

This module is the missing fold layer: a pure matching engine
(``normalize_needle`` / ``compute_class_key`` / ``match_class``) plus one
I/O orchestrator (``file_or_fold``) built entirely on the existing
``PRPort`` surface (``list_issues_by_label`` / ``create_issue`` /
``update_issue_body`` / ``post_comment``) — no new port method, no adapter
mirror sync. A finder whose needle is a pattern (regex/AST shape) calls
``file_or_fold`` once per discovered site; the first call creates ONE
class-level issue carrying an HTML-comment marker
(``<!-- hydraflow-class: KEY --> ``), and every later call for the same
*source* + *needle* folds into that open issue instead of filing a sibling.

Marker convention mirrors the existing ``log_ingest_loop`` /
``adr_conformance_loop`` precedent (issue body is the sole source of truth,
ADR-0041 — no new state file, so lost local state can't re-spawn siblings).
Marker equality is the primary fold signal; because the key embeds a
*truncated* SHA1 digest, marker-equal candidates are also required to share
at least one needle token with the matched issue's own title/body, so a
truncation collision between two genuinely unrelated needles can never
silently merge them (the test-adequacy gap that stalled the first
implementation attempt on this issue). Issues filed before this layer
existed carry no marker; those fold only on title-similarity AND
shared-needle-tokens together — title similarity alone is never sufficient
(over-collapse is the dangerous failure per the design pre-mortem).
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import TYPE_CHECKING

from exception_classify import reraise_on_credit_or_bug

if TYPE_CHECKING:
    from collections.abc import Sequence

    from models import GitHubIssueSummary
    from ports import PRPort

logger = logging.getLogger("hydraflow.find_class_key")

#: Canonical label pattern-shaped findings are filed/searched under.
DEFAULT_FIND_LABEL = "hydraflow-find"

#: Jaccard floor for the legacy (no-marker) title-overlap fallback. Kept
#: conservative per the design pre-mortem: a false fold (merging unrelated
#: defects) is the dangerous failure, not a false negative (an occasional
#: missed fold just means one extra sibling issue — the pre-#11292 status
#: quo, not a regression).
CLASS_OVERLAP_THRESHOLD = 0.5

#: Hex digits of the SHA1 digest kept in a class key. 12 hex chars (48 bits)
#: makes an accidental collision between two real needles negligible for any
#: realistic board size; ``match_class``'s needle-token backstop (see module
#: docstring) is the defense-in-depth for the case where one occurs anyway.
DEFAULT_DIGEST_LEN = 12

_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "are",
        "and",
        "or",
        "for",
        "to",
        "of",
        "in",
        "on",
        "with",
        "still",
        "same",
        "sibling",
        "siblings",
        "issue",
        "issues",
        "src",
        "tests",
        "test",
        "py",
        "md",
        "at",
        "as",
        "from",
        "that",
        "this",
        "these",
        "those",
        "new",
        "old",
        "pr",
    }
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_MARKER_RE = re.compile(r"<!--\s*hydraflow-class:\s*(findclass:\S+?)\s*-->")
_SITES_HEADING = "## Folded sites"


def normalize_needle(text: str) -> frozenset[str]:
    """Token-set for *text* with path/line-number/issue-ref noise stripped.

    Splitting on any non-alphanumeric character already dissolves file
    paths (``src/branch_gc_scan.py:39`` -> ``branch``, ``gc``, ``scan``,
    ``py``, ``39``) and issue references (``#11188`` -> ``11188``); pure
    digit tokens (line numbers, issue numbers) and short/common-repo-word
    tokens are then dropped so two sibling sites normalize to the same
    token set.
    """
    if not text:
        return frozenset()
    tokens = _TOKEN_RE.findall(text.lower())
    return frozenset(
        tok
        for tok in tokens
        if len(tok) >= 3 and not tok.isdigit() and tok not in _STOPWORDS
    )


def compute_class_key(
    source: str, needle: str, *, digest_len: int = DEFAULT_DIGEST_LEN
) -> str:
    """Stable class key for *needle* discovered by *source*.

    Derived from the needle's normalized token set (not the raw string), so
    two sites reporting the same defect with different wording, paths, or
    line numbers produce the IDENTICAL key. ``source`` namespaces the key so
    two unrelated finders never collide even when their needles normalize
    to the same (or an empty) token set.
    """
    tokens = normalize_needle(needle)
    canonical = " ".join(sorted(tokens))
    digest = hashlib.sha1(canonical.encode("utf-8"), usedforsecurity=False).hexdigest()[
        :digest_len
    ]
    safe_source = re.sub(r"[^a-z0-9_-]+", "-", source.lower()).strip("-") or "source"
    return f"findclass:{safe_source}:{digest}"


def render_marker(class_key: str) -> str:
    """Render the HTML-comment marker embedding *class_key* in an issue body."""
    return f"<!-- hydraflow-class: {class_key} -->"


def extract_class_key(body: str) -> str:
    """Return the class key embedded in *body*'s marker, or ``""`` if absent."""
    if not body:
        return ""
    match = _MARKER_RE.search(body)
    return match.group(1) if match else ""


def title_token_overlap(a: str, b: str) -> float:
    """Jaccard similarity of *a* and *b*'s normalized token sets.

    Returns ``0.0`` when either title normalizes to no tokens — an empty
    set can't meaningfully overlap with anything, and treating it as a
    match would let a degenerate title fold into everything.
    """
    tokens_a = normalize_needle(a)
    tokens_b = normalize_needle(b)
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def match_class(
    class_key: str,
    needle: str,
    title: str,
    open_issues: Sequence[GitHubIssueSummary],
) -> int:
    """Return the open issue number *class_key* folds into, or ``0``.

    Marker equality is the primary signal: an open issue whose body carries
    the identical class-key marker is the fold target, GUARDED by a
    needle-token backstop (see module docstring) against a truncated-digest
    collision between two genuinely unrelated needles. Marker-less legacy
    issues fold only when title similarity clears ``CLASS_OVERLAP_THRESHOLD``
    AND the candidate's own needle tokens appear in the issue body — title
    similarity alone is never sufficient.
    """
    needle_tokens = normalize_needle(needle)
    for issue in open_issues:
        body = issue.get("body") or ""
        marker_key = extract_class_key(body)
        if marker_key:
            if marker_key != class_key:
                continue
            candidate_tokens = normalize_needle(
                issue.get("title", "")
            ) | normalize_needle(body)
            if not needle_tokens or (needle_tokens & candidate_tokens):
                return int(issue["number"])
            continue
        overlap = title_token_overlap(title, issue.get("title", ""))
        if (
            overlap >= CLASS_OVERLAP_THRESHOLD
            and needle_tokens
            and (needle_tokens & normalize_needle(body))
        ):
            return int(issue["number"])
    return 0


def _site_line(title: str) -> str:
    return f"- {title}"


def _append_site(body: str, title: str) -> str:
    """Return *body* with *title* appended under the folded-sites section.

    A no-op (returns *body* unchanged) when *title* is already listed — the
    idempotency guard so a re-offered site posts no second comment.
    """
    line = _site_line(title)
    if line in body:
        return body
    if _SITES_HEADING in body:
        return body.rstrip() + "\n" + line + "\n"
    return body.rstrip() + "\n\n" + _SITES_HEADING + "\n" + line + "\n"


async def file_or_fold(
    prs: PRPort,
    source: str,
    needle: str,
    title: str,
    body: str,
    labels: list[str],
    *,
    search_label: str = DEFAULT_FIND_LABEL,
) -> int:
    """File a new class issue, or fold *title*/*body* into the open one.

    Returns the issue number folded into or newly created (``0`` on
    ``create_issue`` failure — the existing 0-sentinel contract callers
    already handle). Listing failures (network/credit) fall through to
    filing fresh rather than raising, matching ``log_ingest_loop``'s
    ``_already_filed`` fail-soft precedent; ``create_issue``'s own
    exact-title dedup remains the last line of defense.
    """
    class_key = compute_class_key(source, needle)
    try:
        open_issues = await prs.list_issues_by_label(search_label)
    except Exception as exc:
        reraise_on_credit_or_bug(exc)
        logger.warning(
            "find_class_key: could not list %r issues for fold check: %s",
            search_label,
            exc,
        )
        open_issues = []

    target = match_class(class_key, needle, title, open_issues)
    if target:
        matched = next(
            (issue for issue in open_issues if issue.get("number") == target), None
        )
        existing_body = (matched or {}).get("body") or ""
        new_body = _append_site(existing_body, title)
        if new_body == existing_body:
            logger.debug(
                "find_class_key: site already folded into #%d, skipping", target
            )
            return target
        await prs.update_issue_body(target, new_body)
        await prs.post_comment(
            target,
            f"Folded a new site into this class issue:\n\n{_site_line(title)}",
        )
        return target

    seeded_body = _append_site(body, title)
    new_body = seeded_body.rstrip() + "\n\n" + render_marker(class_key) + "\n"
    return await prs.create_issue(title, new_body, labels)
