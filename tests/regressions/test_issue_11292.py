"""Regression pin for #11292: pattern-shaped findings fold, not sibling-spawn.

Board-growth analysis found two REAL defect families that each spawned 3
sibling ``hydraflow-find`` issues for ONE underlying defect class:

* branch-name parsers missing the ``agent/auto-agent-<N>`` namespace:
  #11188, #11275, #11281
* non-self-retiring ADR pins in ``tests/regressions/``: #11192, #11193,
  #11195

This pins the actual real titles/bodies (trimmed) from those six issues
through ``find_class_key.file_or_fold`` and asserts each family collapses to
ONE open issue with fold comments for the later sites — the anti-pattern
this issue exists to end.

It also pins the boundary the fold layer must NOT cross: the four
FakeGitHub-fidelity issues (#11227, #11237, #11246, #11247) share a THEME
(the fixture's fidelity gaps) but are four distinct defects, each about a
different ``FakeGitHub`` method. Two of them must stay as separate issues —
folding on theme/title-similarity alone would hide real, unrelated work
(the over-collapse failure the design's pre-mortem calls out).
"""

from __future__ import annotations

import pytest

from find_class_key import file_or_fold


class _RecordingPRPort:
    def __init__(self) -> None:
        self._issues: dict[int, dict] = {}
        self._next_number = 20000
        self.comment_calls: list[tuple[int, str]] = []

    async def list_issues_by_label(self, label: str) -> list[dict]:
        return [dict(issue) for issue in self._issues.values()]

    async def update_issue_body(self, issue_number: int, body: str) -> None:
        self._issues[issue_number]["body"] = body

    async def post_comment(self, issue_number: int, body: str) -> None:
        self.comment_calls.append((issue_number, body))

    async def create_issue(
        self, title: str, body: str, labels: list[str] | None = None
    ) -> int:
        number = self._next_number
        self._next_number += 1
        self._issues[number] = {"number": number, "title": title, "body": body}
        return number


# The finder's own stable description of the pattern it swept for — a real
# finder computes this once per defect class and passes it unchanged across
# every discovered site (only the site-specific title/body vary). This is
# what compute_class_key hashes into the fold marker.
_BRANCH_NAMESPACE_NEEDLE = (
    "branch-to-issue parser recognizes agent/issue- but drops the "
    "agent/auto-agent-<N> namespace"
)
_ADR_PIN_NEEDLE = (
    "regression test hard-codes a docs/adr/NNNN-*.md filename or does a "
    "defaultless ADR-number lookup, exploding on renumbering"
)

# Real (lightly trimmed) titles + body excerpts from the branch-namespace-
# parser family (#11188, #11275, #11281) — one class, three real sites.
_BRANCH_NAMESPACE_SITES = [
    (
        "StaleIssueLoop remote branch GC is blind to the agent/auto-agent-N namespace",
        "src/branch_gc_scan.py:39 _AGENT_BRANCH_RE only matches agent/issue-(\\d+), "
        "missing agent/auto-agent-<N> branches minted by auto_agent_preflight_loop",
    ),
    (
        "hydraflow-find: sibling branch parsers still drop the agent/auto-agent-<N> "
        "namespace (branch_gc_scan, pr_manager)",
        "src/pr_manager.py:3360 _issue_number_from_branch only matches "
        "agent/issue- prefix, dropping agent/auto-agent-<N> branches too",
    ),
    (
        "branch_gc_scan._AGENT_BRANCH_RE misses agent/auto-agent-<N> — StaleIssueLoop "
        "remote reconciliation can't attribute abandoned auto-agent branches",
        "branch_gc_scan._AGENT_BRANCH_RE regex misses agent/auto-agent-<N> branches, "
        "StaleIssueLoop can't reconcile abandoned auto-agent branches",
    ),
]

# Real (lightly trimmed) titles + body excerpts from the non-self-retiring-
# ADR-pin family (#11192, #11193, #11195) — one class, three real sites.
_ADR_PIN_SITES = [
    (
        "tests/regressions/test_issue_9565.py has the same non-self-retiring ADR pin "
        "defect as #11180/#11186",
        "test_issue_9565.py hardcodes docs/adr/0007-dashboard-api-multi-repo-scoping.md "
        "and feeds it to parse_adr_file unconditionally; renumbering ADR-0007 raises "
        "FileNotFoundError in CI on an unrelated PR",
    ),
    (
        "No static guard prevents new tests/regressions ADR pins from hard-coding a "
        "markdown filename",
        "regression tests hard-code a docs/adr/NNNN-*.md filename or do a defaultless "
        "next() lookup by ADR number; nothing stops the next instance from landing",
    ),
    (
        "test_issue_10565.py pins ADR-0013 with a defaultless next() lookup that "
        "explodes on renumbering",
        "test_issue_10565.py:38 does next(a for a in adrs if a.number == 13) with no "
        "default; renumbering or removing ADR-0013 raises an unhandled StopIteration",
    ),
]

# Real (lightly trimmed) titles from the FakeGitHub-fidelity theme — four
# DISTINCT defects, not one class, each with its own stable needle.
_FIDELITY_A = (
    "FakeGitHub tracks no branch refs, so merge/delete-branch behaviour is "
    "untestable at the MockWorld tier",
    "FakeGitHub models PRs but has no branch-ref state; push_branch is a "
    "no-op and delete_branch never emulates delete-branch-on-merge",
)
_FIDELITY_B = (
    "FakeGitHub `gh issue view` ignores the --json selector, returning "
    "{comments: []} for every field set",
    "FakeGitHub._run_gh returns a hardcoded response for gh issue view "
    "regardless of the --json fields requested by the caller",
)


async def _file_family(
    prs: _RecordingPRPort, source: str, needle: str, sites: list[tuple[str, str]]
):
    numbers = []
    for title, body_detail in sites:
        number = await file_or_fold(
            prs,
            source,
            needle,
            title,
            f"## Finding\n\n{body_detail}",
            ["hydraflow-find"],
        )
        numbers.append(number)
    return numbers


@pytest.mark.asyncio
async def test_branch_namespace_parser_family_collapses_to_one_issue() -> None:
    prs = _RecordingPRPort()
    numbers = await _file_family(
        prs,
        "branch-namespace-parser",
        _BRANCH_NAMESPACE_NEEDLE,
        _BRANCH_NAMESPACE_SITES,
    )
    assert len(set(numbers)) == 1
    assert len(prs._issues) == 1
    # Two later sites fold in as comments; the first site creates, not comments.
    assert len(prs.comment_calls) == 2


@pytest.mark.asyncio
async def test_adr_pin_family_collapses_to_one_issue() -> None:
    prs = _RecordingPRPort()
    numbers = await _file_family(
        prs, "adr-pin-guard", _ADR_PIN_NEEDLE, _ADR_PIN_SITES
    )
    assert len(set(numbers)) == 1
    assert len(prs._issues) == 1
    assert len(prs.comment_calls) == 2


@pytest.mark.asyncio
async def test_unrelated_families_never_share_an_issue() -> None:
    prs = _RecordingPRPort()
    branch_numbers = await _file_family(
        prs,
        "branch-namespace-parser",
        _BRANCH_NAMESPACE_NEEDLE,
        _BRANCH_NAMESPACE_SITES,
    )
    adr_numbers = await _file_family(
        prs, "adr-pin-guard", _ADR_PIN_NEEDLE, _ADR_PIN_SITES
    )
    assert set(branch_numbers).isdisjoint(set(adr_numbers))
    assert len(prs._issues) == 2


@pytest.mark.asyncio
async def test_fidelity_theme_distinct_defects_stay_separate_issues() -> None:
    """#11227 and #11246 share a theme (FakeGitHub fidelity), not a class.

    Each targets a different FakeGitHub method with no shared needle tokens
    beyond the generic "fakegithub" word, so they must file as two issues —
    folding them would hide one of the two real, independent fixes.
    """
    prs = _RecordingPRPort()
    title_a, needle_a = _FIDELITY_A
    title_b, needle_b = _FIDELITY_B
    number_a = await file_or_fold(
        prs,
        "fakegithub-fidelity",
        needle_a,
        title_a,
        f"## Finding\n\n{needle_a}",
        ["hydraflow-find"],
    )
    number_b = await file_or_fold(
        prs,
        "fakegithub-fidelity",
        needle_b,
        title_b,
        f"## Finding\n\n{needle_b}",
        ["hydraflow-find"],
    )
    assert number_a != number_b
    assert len(prs._issues) == 2
    assert len(prs.comment_calls) == 0
