"""Tests for wiki_rot_citations helpers (spec §4.9)."""

from __future__ import annotations

from pathlib import Path

from wiki_rot_citations import (
    Cite,
    ShippedClaim,
    extract_cites,
    extract_fenced_hints,
    extract_shipped_claims,
    fuzzy_suggest,
    verify_cite_ast,
    verify_cite_grep,
)


def test_extract_cites_style_a_house() -> None:
    text = "See src/foo.py:bar and tests/helpers/thing.py:Klass."
    got = [(c.module, c.symbol, c.style) for c in extract_cites(text)]
    assert ("src/foo.py", "bar", "colon") in got
    assert ("tests/helpers/thing.py", "Klass", "colon") in got


def test_extract_cites_style_b_dotted() -> None:
    text = "The guard lives in src.repo_wiki.RepoWikiStore."
    got = [(c.module, c.symbol, c.style) for c in extract_cites(text)]
    assert ("src.repo_wiki", "RepoWikiStore", "dotted") in got


def test_extract_cites_does_not_match_dotted_outside_src() -> None:
    # Style-B is anchored to the ``src`` root to avoid over-matching
    # ordinary prose like "the big.bad.wolf".
    assert extract_cites("the big.bad.wolf") == []


def test_extract_cites_dedupes_identical_citations() -> None:
    text = "src/foo.py:bar once. src/foo.py:bar twice."
    got = extract_cites(text)
    assert len(got) == 1


def test_extract_fenced_hints_only_inside_python_blocks() -> None:
    md = (
        "regular prose mentioning foo(\n\n"
        "```python\n"
        "def outer_helper(x): ...\n"
        "class InnerThing: pass\n"
        "outer_helper(1)\n"
        "```\n\n"
        "```\n"
        "def not_a_hint(): ...\n"
        "```\n"
    )
    hints = {h.symbol for h in extract_fenced_hints(md)}
    assert "outer_helper" in hints
    assert "InnerThing" in hints
    assert "not_a_hint" not in hints  # outside a ``python`` fence


def test_verify_cite_ast_present(tmp_path: Path) -> None:
    mod = tmp_path / "src" / "foo.py"
    mod.parent.mkdir(parents=True)
    mod.write_text("def bar():\n    return 1\n\nclass Baz:\n    pass\n")
    ok, symbols = verify_cite_ast(tmp_path, "src/foo.py", "bar")
    assert ok
    assert "bar" in symbols
    assert "Baz" in symbols


def test_verify_cite_ast_missing_symbol(tmp_path: Path) -> None:
    mod = tmp_path / "src" / "foo.py"
    mod.parent.mkdir(parents=True)
    mod.write_text("def other(): ...\n")
    ok, symbols = verify_cite_ast(tmp_path, "src/foo.py", "bar")
    assert not ok
    assert symbols == ["other"]


def test_verify_cite_ast_handles_reexport_depth_1(tmp_path: Path) -> None:
    pkg = tmp_path / "src" / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "_impl.py").write_text("def bar(): ...\n")
    (pkg / "__init__.py").write_text("from ._impl import bar\n")
    ok, _ = verify_cite_ast(tmp_path, "src/pkg/__init__.py", "bar")
    assert ok


def test_verify_cite_ast_missing_module_returns_false(tmp_path: Path) -> None:
    ok, symbols = verify_cite_ast(tmp_path, "src/does_not_exist.py", "bar")
    assert not ok
    assert symbols == []


def test_verify_cite_ast_dotted_style(tmp_path: Path) -> None:
    mod = tmp_path / "src" / "foo.py"
    mod.parent.mkdir(parents=True)
    mod.write_text("class Guard: pass\n")
    cite = Cite(module="src.foo", symbol="Guard", style="dotted", raw="src.foo.Guard")
    ok, _ = verify_cite_ast(tmp_path, cite.module_as_path(), cite.symbol)
    assert ok


def test_verify_cite_grep_hit_and_miss(tmp_path: Path) -> None:
    doc = tmp_path / "docs" / "adr" / "0001.md"
    doc.parent.mkdir(parents=True)
    doc.write_text("See FooBar for details.\n")
    assert verify_cite_grep(tmp_path, "docs/adr/0001.md", "FooBar")
    assert not verify_cite_grep(tmp_path, "docs/adr/0001.md", "Missing")
    # Missing file → False, not exception.
    assert not verify_cite_grep(tmp_path, "does/not/exist.md", "anything")


def test_fuzzy_suggest_close_match() -> None:
    assert fuzzy_suggest("bar", ["baz", "barr", "quux"]) == "barr"


def test_fuzzy_suggest_no_match() -> None:
    assert fuzzy_suggest("zzzzzz", ["alpha", "beta"]) is None


# ---------------------------------------------------------------------------
# Shipped-claim extraction (issue #9598)
# ---------------------------------------------------------------------------


def test_extract_shipped_claims_from_json_entry_block() -> None:
    md = (
        "# Gotcha\n\nSome prose.\n\n"
        "```json:entry\n"
        "{\n"
        '  "id": "example",\n'
        '  "rule": "do the thing",\n'
        '  "code_refs": ["src/foo.py:bar", "src/foo.py:baz"],\n'
        '  "fixed_in_pr": "#8713",\n'
        '  "added": "2026-05-07"\n'
        "}\n"
        "```\n"
    )
    claims = extract_shipped_claims(md)
    assert len(claims) == 1
    claim = claims[0]
    assert isinstance(claim, ShippedClaim)
    assert claim.pr_ref == "#8713"
    assert claim.code_refs == ("src/foo.py:bar", "src/foo.py:baz")


def test_extract_shipped_claims_ignores_entries_without_fixed_in_pr() -> None:
    md = (
        "```json:entry\n"
        '{"id": "compiled", "title": "x", "source_issue": 6295, "stale": false}\n'
        "```\n"
    )
    assert extract_shipped_claims(md) == []


def test_extract_shipped_claims_ignores_source_footer_prose() -> None:
    # ``_Source: #6295 (plan)_`` footers are provenance, not shipped claims.
    md = "# Entry\n\nBody text.\n\n_Source: #6295 (plan)_\n"
    assert extract_shipped_claims(md) == []


def test_extract_shipped_claims_handles_missing_code_refs() -> None:
    md = '```json:entry\n{"id": "x", "fixed_in_pr": "#9001"}\n```\n'
    claims = extract_shipped_claims(md)
    assert len(claims) == 1
    assert claims[0].pr_ref == "#9001"
    assert claims[0].code_refs == ()


def test_extract_shipped_claims_tolerates_malformed_json() -> None:
    md = (
        "```json:entry\n"
        "{ this is not valid json,, }\n"
        "```\n"
        "```json:entry\n"
        '{"id": "ok", "fixed_in_pr": "#42", "code_refs": ["src/x.py:y"]}\n'
        "```\n"
    )
    claims = extract_shipped_claims(md)
    assert len(claims) == 1
    assert claims[0].pr_ref == "#42"


def test_extract_shipped_claims_multiple_blocks() -> None:
    md = (
        "```json:entry\n"
        '{"id": "a", "fixed_in_pr": "#1", "code_refs": ["src/a.py:f"]}\n'
        "```\n"
        "```json:entry\n"
        '{"id": "b", "fixed_in_pr": "#2", "code_refs": ["src/b.py:g"]}\n'
        "```\n"
    )
    claims = extract_shipped_claims(md)
    assert {c.pr_ref for c in claims} == {"#1", "#2"}


def test_extract_shipped_claims_skips_blank_fixed_in_pr() -> None:
    md = (
        "```json:entry\n"
        '{"id": "x", "fixed_in_pr": "", "code_refs": ["src/x.py:y"]}\n'
        "```\n"
    )
    assert extract_shipped_claims(md) == []
