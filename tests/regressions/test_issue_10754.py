"""Regression for issue #10754.

Wiki entries instructed readers to run `wiki_lesson_coverage` to tier
`left_on_primary` predecessors, but at the time no such module or script
existed — it was a `source_phase: plan` reference to tooling that had not
shipped, and `extract_cites` was blind to bare backticked tool names in
prose so the dead-end guidance survived undetected.

Resolution landed in two parts that now meet on `staging`:

1. PR #10772 (the lesson-survival cluster) shipped the real tool —
   `src/wiki_lesson_coverage.py` + the CLI `scripts/audit_wiki_lesson_coverage.py`.
   So `wiki_lesson_coverage` is now a VALID citation, not a phantom.
2. This change added Style-D (#10762): a bare backticked tool name in
   imperative position ("Run `wiki_lesson_coverage`") is extracted and
   resolved by presence against the symbol corpus.

The point of #10754 therefore INVERTS: the corpus-wide scan now finds zero
*dead* bare tool-cites because the tool **exists** (Style-D resolves it),
not because the references were stripped from the wiki. These tests pin that
inversion — if the tool were ever removed again, `wiki_lesson_coverage` would
resolve nowhere and Style-D would (correctly) flag the live entries that cite
it.
"""

from __future__ import annotations

from pathlib import Path

from wiki_rot_citations import build_symbol_corpus, extract_cites, resolve_bare_cite

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_lesson_coverage_tool_now_exists() -> None:
    # #10754 is resolved by the tool existing (PR #10772), not by pruning refs.
    assert (_REPO_ROOT / "src" / "wiki_lesson_coverage.py").is_file()
    assert (_REPO_ROOT / "scripts" / "audit_wiki_lesson_coverage.py").is_file()


def test_wiki_lesson_coverage_resolves_in_corpus() -> None:
    corpus = build_symbol_corpus(_REPO_ROOT)
    # The module stem + CLI stem are both real names now, so an imperative
    # bare cite to either resolves rather than flagging as rot.
    assert resolve_bare_cite("wiki_lesson_coverage", corpus) is True
    assert resolve_bare_cite("audit_wiki_lesson_coverage", corpus) is True


def test_imperative_cite_to_the_tool_is_not_broken() -> None:
    corpus = build_symbol_corpus(_REPO_ROOT)
    text = "Run `wiki_lesson_coverage` to tier left_on_primary predecessors."
    bare = [c for c in extract_cites(text) if c.style == "bare"]
    assert bare and bare[0].symbol == "wiki_lesson_coverage"
    # Style-D extracts it, but it now RESOLVES — so the detector reports no rot.
    assert all(resolve_bare_cite(c.symbol, corpus) for c in bare)


def test_no_dead_bare_tool_cites_across_live_wiki() -> None:
    # The end state #10754 asked for: every Style-D bare tool-cite in the live
    # corpus resolves. Zero dead tool-cites — because the tools exist, not
    # because references were removed.
    corpus = build_symbol_corpus(_REPO_ROOT)
    wiki_root = _REPO_ROOT / "repo_wiki"
    dead: list[str] = []
    for md in wiki_root.rglob("*.md"):
        text = md.read_text(encoding="utf-8", errors="replace")
        for cite in extract_cites(text):
            if cite.style == "bare" and not resolve_bare_cite(cite.symbol, corpus):
                dead.append(f"{md.relative_to(_REPO_ROOT).as_posix()}: {cite.symbol}")
    assert dead == [], f"dead bare tool-cites still in wiki: {dead}"
