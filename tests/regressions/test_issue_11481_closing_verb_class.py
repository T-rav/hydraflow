r"""Regression pins for the #11481 closing-verb-parser class.

GitHub auto-closes an issue on any of *nine* closing-keyword forms —
``close``/``closes``/``closed``, ``fix``/``fixes``/``fixed``,
``resolve``/``resolves``/``resolved``. Four sites had hand-copied a narrowed
``(?:fixes|closes|resolves)\s+#(\d+)`` covering only the third-person-singular
third of that set, and (lacking ``\b`` boundaries) false-matching
``prefixes #99``:

* ``src/branch_gc_scan.py`` (``_FIXES_RE``) — ``extract_issue_number`` returned
  ``0`` for a ``Fixed #N`` commit, so ``classify_branch`` reported
  ``no_reference`` and ``StaleIssueLoop``'s ``if issue_number <= 0: continue``
  skipped the truth-comment/delete-reconcile pass for exactly the false
  "fix applied" branches branch-GC exists to catch. This is the reported bug.
* ``src/pr_manager.py`` (``merge_pr`` title parse) — a ``Fixed #12`` title fell
  through to the first bare ``#N``, attributing merge cost to the wrong issue.
* ``src/pr_manager.py`` (``find_label_drift``) — label drift on a
  ``Resolved #N`` PR body went undetected.
* ``src/pr_manager.py`` (``find_open_resolving_pr``) — a ``Fixed #N`` PR body
  did not count as a resolving link, so a stale escalation label could
  re-trigger an auto-agent attempt against an already-open PR.

Two further sites carried the full verb set but as their own hand-rolled
copies — behaviourally near-equivalent, yet they kept the duplication class
open. Both are folded onto the canonical object too:

* ``src/escape/attribution.py`` — its own verb alternation.
* ``src/arch/generators/traceability_matrix.py`` — the canonical pattern with
  a named group and no trailing ``\b``, found by review of this fix.

The fix is *reuse*, not re-derivation: every site imports
``false_close.CLOSE_KEYWORD_RE``. The identity pins are the load-bearing part
of this file — an equivalent-but-separate local copy would satisfy every
behavioural pin while silently re-opening the class, so identity (``is``) is
asserted rather than mere equality.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import branch_gc_scan
import false_close
import pr_manager
from arch.generators import traceability_matrix
from branch_gc_scan import extract_issue_number
from escape import attribution
from false_close import CLOSE_KEYWORD_RE
from tests.helpers import make_pr_manager

REPO_ROOT = Path(__file__).resolve().parents[2]

# Every closing-keyword form GitHub itself honours: three verbs x
# {bare, third-person-singular, past tense}.
CLOSING_VERBS = (
    "close",
    "closes",
    "closed",
    "fix",
    "fixes",
    "fixed",
    "resolve",
    "resolves",
    "resolved",
)

# Shape of a hand-rolled closing-keyword parser: a regex literal naming a
# closing verb somewhere ahead of a ``#<digits>`` capture. Deliberately NOT
# the exact narrowed literal this issue removed — a needle that specific
# would have missed both shapes the fix itself deleted (``attribution``'s
# full-verb alternation and the arch generator's named-group copy), so it
# would have reported "class closed" while live duplicates survived.
HANDROLLED_SHAPE_RE = re.compile(r"(?:close|fix|resolve)[^\n]{0,80}?#\(", re.IGNORECASE)

# ``false_close`` is where the one definition is allowed to live.
CANONICAL_MODULE = "src/false_close.py"


def _regex_literals(source: str) -> list[str]:
    """Every string literal in *source* — regex patterns included."""
    try:
        tree = ast.parse(source)
    except SyntaxError:  # pragma: no cover - src/ is always parseable
        return []
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


# --------------------------------------------------------------------------
# Identity pins — the part a behaviourally-equivalent local copy would pass.
# --------------------------------------------------------------------------


def test_branch_gc_scan_reuses_the_canonical_regex_object() -> None:
    """Identity, not equality: a local copy that happens to be equivalent
    today would re-open the class the moment either side is edited."""
    assert branch_gc_scan.CLOSE_KEYWORD_RE is false_close.CLOSE_KEYWORD_RE


def test_pr_manager_reuses_the_canonical_regex_object() -> None:
    assert pr_manager.CLOSE_KEYWORD_RE is false_close.CLOSE_KEYWORD_RE


def test_attribution_reuses_the_canonical_regex_object() -> None:
    """The fifth site: full verb set, but its own alternation (#11481 step 4)."""
    assert attribution.CLOSE_KEYWORD_RE is false_close.CLOSE_KEYWORD_RE


def test_traceability_matrix_reuses_the_canonical_regex_object() -> None:
    """The sixth site: the canonical pattern re-spelled with a named group."""
    assert traceability_matrix.CLOSE_KEYWORD_RE is false_close.CLOSE_KEYWORD_RE


def test_false_close_is_the_only_module_defining_the_grammar() -> None:
    """Class-closure pin: exactly one module under ``src/`` may spell out a
    closing-verb-plus-``#(digits)`` regex. Six sites had re-derived it in
    four different spellings, so this asserts on the *shape* rather than on
    any one narrowed literal."""
    offenders = sorted(
        rel
        for path in (REPO_ROOT / "src").rglob("*.py")
        if (rel := str(path.relative_to(REPO_ROOT))) != CANONICAL_MODULE
        and any(
            HANDROLLED_SHAPE_RE.search(literal)
            for literal in _regex_literals(path.read_text(encoding="utf-8"))
        )
    )
    assert offenders == [], (
        f"Closing-keyword grammar re-derived in: {offenders}. "
        "Import false_close.CLOSE_KEYWORD_RE (or closing_issue_refs) instead."
    )


# --------------------------------------------------------------------------
# Generator pin — the whole verb set, through the canonical object.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("verb", CLOSING_VERBS)
def test_canonical_regex_covers_every_closing_verb_form(verb: str) -> None:
    for text in (
        f"{verb} #1234",
        f"{verb.capitalize()} #1234",
        f"{verb.upper()} #1234",
    ):
        assert CLOSE_KEYWORD_RE.findall(text) == ["1234"], f"{text!r} must match"


def test_canonical_regex_rejects_verb_substrings() -> None:
    """The narrowed copies lacked ``\\b``, so ``prefixes #99`` false-matched."""
    for text in ("prefixes #99", "suffixes #99", "unfixed #99", "postfix #99"):
        assert CLOSE_KEYWORD_RE.findall(text) == [], f"{text!r} must not match"


def test_canonical_regex_rejects_conventional_commit_prefix() -> None:
    """``fix: subject`` is a type prefix, not a closing reference."""
    assert CLOSE_KEYWORD_RE.findall("fix: tidy up, see #99") == []


# --------------------------------------------------------------------------
# Behavioural pin, site 1 — branch_gc_scan.extract_issue_number.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("verb", CLOSING_VERBS)
def test_gc_extractor_resolves_every_closing_verb_form(verb: str) -> None:
    assert extract_issue_number("fix/x", [f"{verb.capitalize()} #1234"]) == 1234


def test_gc_extractor_resolves_the_reported_past_tense_case() -> None:
    """The literal case from the issue report."""
    assert extract_issue_number("fix/x", ["Resolved #1234"]) == 1234
    assert extract_issue_number("fix/y", ["Fixed #1234"]) == 1234


# --------------------------------------------------------------------------
# Behavioural pin, site 2 — pr_manager.merge_pr cost attribution.
# --------------------------------------------------------------------------


def _stub_pricing() -> object:
    """Sentinel pricing object for monkeypatching ``load_pricing``."""
    return object()


@pytest.fixture
def merge_cfg(tmp_path: Path) -> MagicMock:
    cfg = MagicMock()
    cfg.data_root = tmp_path
    cfg.data_path = tmp_path.joinpath
    cfg.dry_run = False
    cfg.repo = "owner/repo"
    cfg.repo_root = tmp_path
    cfg.find_label = ["hydraflow-find"]
    cfg.issue_cost_alert_usd = 1.0
    cfg.daily_cost_budget_usd = None
    cfg.gh_max_retries = 0
    return cfg


@pytest.fixture
def _stub_pr_diff_stats(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _empty(_self: object, _pr_number: int) -> dict[str, object]:
        return {}

    monkeypatch.setattr("pr_manager.PRManager.get_pr_diff_stats", _empty)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        # The bare "#N" must PRECEDE the closing reference for the narrowed
        # regex to actually misbehave: with the verb first, the "first bare #N"
        # fallback lands on the right issue by coincidence and pins nothing.
        ("Part of #34 - Fixed #12: address the thing", 12),
        ("Tracked by #34 - Closed #56: cleanup", 56),
        ("Epic #34: Resolved #90 for the reporter", 90),
        ("Rollup #34 - Fix #21: quick patch", 21),
        ("[#34] Close #22 see background", 22),
        ("chore(#34): Resolve #23 relates to that", 23),
        # Liveness: the three forms the narrowed regex already covered still
        # anchor, so this is a widening and not a rewrite.
        ("Part of #34 - Fixes #12: address the thing", 12),
        ("refactor: tidy (closes #7)", 7),
        # Liveness: the keyword-less fallback to the first bare "#N" survives.
        ("feat(x): do thing (#123)", 123),
    ],
)
async def test_merge_cost_anchors_on_every_closing_verb_form(
    title: str,
    expected: int,
    merge_cfg: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    _stub_pr_diff_stats: None,
) -> None:
    """Merge cost bills the issue the PR *closes*, not the first ``#N`` seen.

    With the narrowed regex, a title like ``Part of #34 - Fixed #12`` found no
    anchored match (``Fixed`` was outside the ``Fixes|Closes|Resolves`` set),
    fell through to the first bare ``#N``, and billed the merge to the epic
    (#34) instead of the fixed issue (#12).
    """
    captured: list[int] = []

    async def fake_check_issue_cost(_cfg, *, issue_number, **_kw):
        captured.append(issue_number)

    manager = pr_manager.PRManager(
        config=merge_cfg, event_bus=MagicMock(publish=AsyncMock())
    )
    monkeypatch.setattr(
        manager, "get_pr_title_and_body", AsyncMock(return_value=(title, ""))
    )
    monkeypatch.setattr("pr_manager.run_subprocess", AsyncMock())
    monkeypatch.setattr("pr_manager.load_pricing", _stub_pricing)
    monkeypatch.setattr(
        "pr_manager.iter_priced_inferences_for_issue", lambda *_a, **_kw: iter([])
    )
    monkeypatch.setattr("pr_manager.check_issue_cost", fake_check_issue_cost)

    assert await manager.merge_pr(0) is True
    assert captured == [expected]


# --------------------------------------------------------------------------
# Behavioural pin, site 3 — pr_manager.find_label_drift.
# --------------------------------------------------------------------------


def _gh_responder(mapping: dict[tuple[str, ...], str]):
    async def _side_effect(*args, **_kwargs):
        for key, response in mapping.items():
            if all(part in args for part in key):
                return response
        raise AssertionError(f"unexpected gh call: {args}")

    return _side_effect


@pytest.mark.parametrize("verb", CLOSING_VERBS)
async def test_label_drift_detects_every_closing_verb_form(
    verb: str, config, event_bus
) -> None:
    manager = make_pr_manager(config, event_bus)
    prs_json = json.dumps(
        [
            {
                "number": 500,
                "labels": [{"name": "hydraflow-review"}],
                "body": f"## Summary\n\n{verb.capitalize()} #42.\n",
            }
        ]
    )

    with patch(
        "pr_manager.run_subprocess_with_retry",
        new=AsyncMock(
            side_effect=_gh_responder(
                {
                    ("pr", "list"): prs_json,
                    ("pr", "view"): json.dumps({"commits": [{"oid": "1"}]}),
                    ("issue", "view"): json.dumps(
                        {"labels": [{"name": "hydraflow-ready"}]}
                    ),
                }
            )
        ),
    ):
        drift = await manager.find_label_drift()

    assert len(drift) == 1, f"{verb!r} must count as an auto-close link"
    assert drift[0].issue == 42


# --------------------------------------------------------------------------
# Behavioural pin, site 4 — pr_manager.find_open_resolving_pr.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("verb", CLOSING_VERBS)
async def test_find_open_resolving_pr_accepts_every_closing_verb_form(
    verb: str, config, event_bus
) -> None:
    manager = make_pr_manager(config, event_bus)
    prs_json = json.dumps(
        [{"number": 500, "body": f"## Summary\n\n{verb.capitalize()} #42.\n"}]
    )

    with patch(
        "pr_manager.run_subprocess_with_retry",
        new=AsyncMock(return_value=prs_json),
    ):
        result = await manager.find_open_resolving_pr(42)

    assert result == 500, f"{verb!r} must count as a resolving link"


# --------------------------------------------------------------------------
# Site 5 — escape/attribution equivalence, so the fold is provably safe.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("verb", CLOSING_VERBS)
def test_attribution_still_extracts_every_closing_verb_form(verb: str) -> None:
    assert attribution.extract_fixes_refs(f"{verb.capitalize()} #77") == [77]


def test_attribution_fold_preserves_ordering_and_dedup() -> None:
    """The behaviour ``extract_fixes_refs`` promises beyond raw matching."""
    text = "Fixed #12 and closes #34; also Resolved #12 again."
    assert attribution.extract_fixes_refs(text) == [12, 34]


def test_attribution_fold_rejects_malformed_trailing_word_refs() -> None:
    """The one input where the canonical regex is *stricter* than the local
    alternation it replaces: its trailing ``\\b`` rejects ``#123abc``, which
    GitHub would not treat as a reference to issue 123 either. Pinned so the
    divergence stays deliberate rather than an accident of the fold."""
    assert attribution.extract_fixes_refs("fixes #123abc") == []
    assert attribution.extract_fixes_refs("fixes #123.") == [123]


# --------------------------------------------------------------------------
# Liveness counter-pins — proof the widened parser did not become "match all".
# --------------------------------------------------------------------------


def test_absent_closing_reference_still_yields_zero() -> None:
    """``0`` is the signal ``StaleIssueLoop`` skips on; it must still be
    reachable, or branch-GC would comment on an arbitrary issue."""
    assert extract_issue_number("fix/x", []) == 0
    assert extract_issue_number("fix/x", ["chore: tidy imports"]) == 0
    assert extract_issue_number("fix/x", ["see #42 for context"]) == 0
    assert extract_issue_number("fix/x", ["prefixes #99 are unrelated"]) == 0


def test_branch_name_resolution_still_wins_over_commit_messages() -> None:
    """#11281's pins must survive: both mint patterns beat commit scanning."""
    assert extract_issue_number("agent/issue-42", ["Fixed #999"]) == 42
    assert extract_issue_number("agent/auto-agent-42", ["Fixed #999"]) == 42


def test_newest_first_commit_ordering_still_wins() -> None:
    assert (
        extract_issue_number("fix/x", ["Fixed #2: latest", "Fixes #1: original"]) == 2
    )
