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
at least one needle token with the matched issue's own title/body AND clear
a title-affinity floor (``CLASS_MARKER_TITLE_FLOOR``) against that issue's
title, so a truncation collision between two genuinely unrelated needles can
never silently merge them on a single coincidental shared word (the
test-adequacy gap that stalled the first implementation attempt on this
issue). Issues filed before this layer existed carry no marker; those fold
only on title-similarity AND shared-needle-tokens together — title
similarity alone is never sufficient (over-collapse is the dangerous
failure per the design pre-mortem).

Cross-tick idempotency (#11328) keys off an explicit *site* identifier
(e.g. ``file:line``) rather than the site's title text: ``file_or_fold``
and ``_append_site`` accept an optional ``site`` kwarg, and
``extract_folded_sites`` reads the current roster back out of an issue
body. A rediscovered site is then a true no-op even if the finder reworded
its title between ticks; callers that omit ``site`` keep the pre-#11328
title-keyed behavior unchanged.

A site-aware call can still land on a legacy, untagged roster line whose
title text happens to match (title uniqueness per site was never
guaranteed). ``_append_site`` resolves that by BINDING the legacy line to
the current call's site (#11407) rather than either no-op'ing outright
(which could silently drop a genuinely different, same-titled site forever)
or appending a duplicate entry (which would break the intended #11328
same-site idempotency). Binding changes the issue body but leaves the
roster's entry count unchanged, which ``file_or_fold`` uses to decide
whether the fold warrants a "new site" comment.
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

#: Title-token-overlap floor for the marker-equality fold path. A shared
#: needle token alone is not sufficient evidence two issues are the same
#: class (a single common word is easy to hit by chance); the marker path
#: also requires the candidate's title to clear this floor against the
#: matched issue's title. Calibrated below the tightest real same-class pair
#: in ``tests/regressions/test_issue_11292.py`` (~0.07 title-token overlap
#: between that family's first and last sibling titles) so real folds are
#: unaffected, while a title that shares no meaningful content with the
#: matched issue's title is refused even if one needle token collides.
CLASS_MARKER_TITLE_FLOOR = 0.05

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
_SITE_LINE_RE = re.compile(r"^- (.*?)(?: \(site: `([^`]+)`\))?$")


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
    the identical class-key marker is the fold target, GUARDED by BOTH a
    needle-token backstop (see module docstring) against a truncated-digest
    collision between two genuinely unrelated needles AND a title-affinity
    floor (``CLASS_MARKER_TITLE_FLOOR``) — a single shared needle token is
    not sufficient evidence of class membership on its own. Marker-less
    legacy issues fold only when title similarity clears
    ``CLASS_OVERLAP_THRESHOLD`` AND the candidate's own needle tokens appear
    in the issue body — title similarity alone is never sufficient.
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
            needle_backstop = not needle_tokens or (needle_tokens & candidate_tokens)
            title_affinity = title_token_overlap(title, issue.get("title", ""))
            if needle_backstop and title_affinity >= CLASS_MARKER_TITLE_FLOOR:
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


def extract_folded_sites(body: str) -> list[str]:
    """Return the site identifiers already folded into *body*, in order.

    Reads the ``## Folded sites`` section rendered by :func:`_append_site`.
    A line rendered with an explicit site identifier (``- title (site:
    `X`)``) yields ``X``; a legacy line with no tag (``- title``, from
    before per-site identifiers existed, or from a caller that never passed
    one) yields its own title text as the identifier — the pre-#11328
    fold behavior, preserved so old and new lines dedupe consistently.
    """
    if not body or _SITES_HEADING not in body:
        return []
    _, _, section = body.partition(_SITES_HEADING)
    sites = []
    for raw_line in section.splitlines():
        line = raw_line.strip()
        if not line:
            if sites:
                break
            continue
        match = _SITE_LINE_RE.match(line)
        if not match:
            break
        title, site = match.group(1), match.group(2)
        sites.append(site if site is not None else title)
    return sites


def _single_line(text: str) -> str:
    """Collapse *text* to one line with no backticks.

    ``_site_line`` renders *title*/*site* into a single ``- ...`` markdown
    bullet that :data:`_SITE_LINE_RE` must parse back out; an embedded
    newline splits it across lines (truncating every later roster entry,
    since :func:`extract_folded_sites` stops at the first non-bullet line)
    and an embedded backtick breaks the ``` `site` ``` delimiter match. Both
    are stripped here so a title/site can never corrupt the roster it's
    rendered into.
    """
    return " ".join(text.replace("`", "'").split())


def _site_line(title: str, site: str | None = None) -> str:
    title = _single_line(title)
    if site is not None and site != title:
        return f"- {title} (site: `{_single_line(site)}`)"
    return f"- {title}"


def _append_site(body: str, title: str, site: str | None = None) -> str:
    """Return *body* with *title*/*site* appended under the folded-sites section.

    A no-op (returns *body* unchanged) when *site* (or, absent an explicit
    *site*, *title*) is already rostered — the idempotency guard so a
    re-offered site posts no second comment, even if the finder reworded
    the title text between ticks (#11328).

    When *title* matches a legacy, untagged roster line instead (issues
    filed before per-site identifiers existed roster sites by title text
    alone — :func:`extract_folded_sites` yields that title as the entry's
    identifier), the call is BOUND to that line rather than either
    no-op'd outright or appended as a second entry (#11407): title text
    alone can't prove the current *site* is the one that originally
    created the legacy line, since a templated/generic finder can produce
    the same title for a genuinely different site. Binding rewrites the
    legacy line to carry *site*'s tag, so the site is never silently
    dropped from tracking even in the collision case, while a true
    same-site rediscovery still leaves the roster's entry COUNT unchanged
    (:func:`file_or_fold` uses that to decide whether a "new site" comment
    is warranted).
    """
    title = _single_line(title)
    effective_site = _single_line(site) if site is not None else title
    existing_sites = extract_folded_sites(body)
    if effective_site in existing_sites:
        return body
    if site is not None and title in existing_sites:
        bound = _bind_bare_line(body, title, effective_site)
        if bound is not None:
            return bound

    line = _site_line(title, site)
    if _SITES_HEADING not in body:
        return body.rstrip() + "\n\n" + _SITES_HEADING + "\n" + line + "\n"

    # Insert right after the last existing site line, NOT at the end of the
    # whole body — content can follow the sites section (e.g. the class-key
    # marker rendered by file_or_fold on the seeding call), and appending
    # past it would break the contiguous list extract_folded_sites expects.
    head, _, rest = body.partition(_SITES_HEADING)
    section_lines = rest.split("\n")
    insert_at = 1
    while insert_at < len(section_lines) and section_lines[insert_at].startswith("- "):
        insert_at += 1
    section_lines.insert(insert_at, line)
    return head + _SITES_HEADING + "\n".join(section_lines)


def _bind_bare_line(body: str, title: str, effective_site: str) -> str | None:
    """Rewrite the bare ``- {title}`` roster line to carry *effective_site*.

    Returns ``None`` if no literal bare line matches *title* — defensive
    fallback so a caller (:func:`_append_site`) falls through to appending
    a fresh line rather than silently discarding the site when the
    membership check that routed here (``title in existing_sites``) was
    satisfied by something other than an actual bare line (e.g. a tagged
    line whose own site value happens to equal *title*).
    """
    bare_line = f"- {title}"
    head, _, rest = body.partition(_SITES_HEADING)
    section_lines = rest.split("\n")
    # Bounded to the contiguous roster block only, mirroring the insert-loop
    # boundary above -- content can follow the sites section (e.g. the
    # class-key marker, or unrelated later headings/bullets), and matching
    # a bare line out there would rewrite unrelated body content instead of
    # correctly falling through to appending a fresh roster entry.
    roster_end = 1
    while roster_end < len(section_lines) and section_lines[roster_end].startswith(
        "- "
    ):
        roster_end += 1
    for i in range(1, roster_end):
        if section_lines[i].strip() == bare_line:
            section_lines[i] = _site_line(title, effective_site)
            return head + _SITES_HEADING + "\n".join(section_lines)
    return None


async def file_or_fold(
    prs: PRPort,
    source: str,
    needle: str,
    title: str,
    body: str,
    labels: list[str],
    *,
    site: str | None = None,
    search_label: str = DEFAULT_FIND_LABEL,
) -> int:
    """File a new class issue, or fold *title*/*body* into the open one.

    *site* is a stable per-discovery identifier (e.g. ``file:line``) used
    for idempotency instead of *title* text, so a re-discovered site folds
    as a no-op even when the finder reworded its title between ticks
    (#11328). When omitted, idempotency falls back to *title* itself —
    identical to the pre-#11328 behavior.

    A legacy (pre-#11292) issue folded into via the marker-less
    title-overlap path gets the class-key marker stamped onto it here, so
    the NEXT tick matches it via the stronger, more reliable marker-equality
    path in :func:`match_class` instead of re-clearing
    ``CLASS_OVERLAP_THRESHOLD`` every time.

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
        new_body = _append_site(existing_body, title, site)
        if new_body == existing_body:
            logger.debug(
                "find_class_key: site already folded into #%d, skipping", target
            )
            return target
        # A legacy bare-line bind (#11407) changes the body but leaves the
        # roster's entry COUNT unchanged -- it's resolving an existing
        # entry's identifier, not adding a new one, so it shouldn't post a
        # "new site" comment. Only an actual roster growth warrants one.
        is_new_site = len(extract_folded_sites(new_body)) > len(
            extract_folded_sites(existing_body)
        )
        if not extract_class_key(new_body):
            # Legacy (pre-#11292) issue matched via the marker-less
            # title-overlap path -- stamp the marker now so future ticks
            # fold via marker equality instead of re-clearing the overlap
            # threshold every time.
            new_body = new_body.rstrip() + "\n\n" + render_marker(class_key) + "\n"
        await prs.update_issue_body(target, new_body)
        if is_new_site:
            await prs.post_comment(
                target,
                f"Folded a new site into this class issue:\n\n{_site_line(title, site)}",
            )
        return target

    seeded_body = _append_site(body, title, site)
    new_body = seeded_body.rstrip() + "\n\n" + render_marker(class_key) + "\n"
    return await prs.create_issue(title, new_body, labels)
