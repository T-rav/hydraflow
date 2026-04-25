"""Symbol-level precision for the ADR touchpoint gate.

Today the gate fires whenever any cited file is touched, even if the
edit is unrelated to what the ADR covers (e.g. removing an unused
parameter from ``src/agent.py`` drags in ADR-0024 + ADR-0027).

Per-ADR file citations already accept a ``:Symbol`` suffix
(``src/foo.py:Bar``).  When a citation is symbol-qualified, the gate
should only fire when the diff actually changes that symbol.  Bare
file citations (``src/foo.py``) keep firing unconditionally —
backwards-compatible.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from check_adr_touchpoints import (  # noqa: E402
    _changed_symbols_in_file,
    evaluate_gate,
)

from adr_index import ADR, ADRIndex  # noqa: E402

# ---------------------------------------------------------------------------
# Citation parsing — symbol_citations is populated from `src/...:Symbol`
# ---------------------------------------------------------------------------


def _write_adr(
    adr_dir: Path,
    number: int,
    title: str,
    citations: list[str],
    *,
    status: str = "Accepted",
) -> Path:
    adr_dir.mkdir(parents=True, exist_ok=True)
    path = adr_dir / f"{number:04d}-{title.lower().replace(' ', '-')}.md"
    cite_lines = "\n".join(f"- `{c}`" for c in citations)
    path.write_text(
        f"# ADR-{number:04d}: {title}\n\n"
        f"**Status:** {status}\n"
        f"**Date:** 2026-04-25\n\n"
        f"## Context\n\nFixture.\n\n"
        f"## Related\n\n{cite_lines}\n"
    )
    return path


class TestSymbolCitationParsing:
    def test_symbol_qualified_citation_populates_symbol_set(
        self, tmp_path: Path
    ) -> None:
        _write_adr(tmp_path, 1, "A", ["src/foo.py:Bar"])
        adr = next(a for a in ADRIndex(tmp_path).adrs() if a.number == 1)

        assert adr.source_symbols == {"src/foo.py": frozenset({"Bar"})}
        assert "src/foo.py" in adr.source_files

    def test_dotted_symbol_citation_is_captured_intact(self, tmp_path: Path) -> None:
        """``Bar.method`` must round-trip — many ADRs cite class.method."""
        _write_adr(tmp_path, 1, "A", ["src/foo.py:Bar.method"])
        adr = next(a for a in ADRIndex(tmp_path).adrs() if a.number == 1)

        assert adr.source_symbols == {"src/foo.py": frozenset({"Bar.method"})}

    def test_multiple_symbols_for_same_file_accumulate(self, tmp_path: Path) -> None:
        _write_adr(
            tmp_path, 1, "A", ["src/foo.py:Bar", "src/foo.py:Baz", "src/foo.py:Qux"]
        )
        adr = next(a for a in ADRIndex(tmp_path).adrs() if a.number == 1)

        assert adr.source_symbols == {
            "src/foo.py": frozenset({"Bar", "Baz", "Qux"}),
        }

    def test_bare_citation_marks_file_with_empty_symbol_set(
        self, tmp_path: Path
    ) -> None:
        """A bare file citation signals 'fire on any change'."""
        _write_adr(tmp_path, 1, "A", ["src/foo.py"])
        adr = next(a for a in ADRIndex(tmp_path).adrs() if a.number == 1)

        # File present in source_files; symbol set is empty (= bare).
        assert "src/foo.py" in adr.source_files
        assert adr.source_symbols.get("src/foo.py") == frozenset()

    def test_mixed_bare_and_symbol_for_same_file_collapses_to_bare(
        self, tmp_path: Path
    ) -> None:
        """If even one citation is bare, the file is treated as bare."""
        _write_adr(tmp_path, 1, "A", ["src/foo.py:Bar", "src/foo.py"])
        adr = next(a for a in ADRIndex(tmp_path).adrs() if a.number == 1)

        # bare wins → empty set means 'any change fires'
        assert adr.source_symbols.get("src/foo.py") == frozenset()


# ---------------------------------------------------------------------------
# Symbol-diff extraction — what the gate uses to know what changed
# ---------------------------------------------------------------------------


class TestChangedSymbolExtraction:
    """``_changed_symbols_in_file`` returns the set of changed top-level
    and method symbols between two AST snapshots."""

    def test_modified_function_body_is_flagged(self) -> None:
        before = "def foo():\n    return 1\n"
        after = "def foo():\n    return 2\n"
        assert _changed_symbols_in_file(before, after) == {"foo"}

    def test_added_function_is_flagged(self) -> None:
        before = "def foo():\n    return 1\n"
        after = "def foo():\n    return 1\n\ndef bar():\n    return 2\n"
        assert _changed_symbols_in_file(before, after) == {"bar"}

    def test_removed_function_is_flagged(self) -> None:
        before = "def foo():\n    return 1\n\ndef bar():\n    return 2\n"
        after = "def foo():\n    return 1\n"
        assert _changed_symbols_in_file(before, after) == {"bar"}

    def test_modified_method_is_flagged_with_dotted_name(self) -> None:
        before = "class Bar:\n    def m(self):\n        return 1\n"
        after = "class Bar:\n    def m(self):\n        return 2\n"
        # Both Bar.m (the method) AND Bar (the class as a whole) change
        # because the class's full source text differs.
        assert "Bar.m" in _changed_symbols_in_file(before, after)
        assert "Bar" in _changed_symbols_in_file(before, after)

    def test_pure_import_change_does_not_flag_any_symbol(self) -> None:
        """Adding/removing an import is not a symbol change."""
        before = "import os\n\ndef foo():\n    return 1\n"
        after = "import os\nimport sys\n\ndef foo():\n    return 1\n"
        assert _changed_symbols_in_file(before, after) == set()

    def test_pure_module_docstring_change_does_not_flag_any_symbol(self) -> None:
        before = '"""Old."""\n\ndef foo():\n    return 1\n'
        after = '"""New."""\n\ndef foo():\n    return 1\n'
        assert _changed_symbols_in_file(before, after) == set()

    def test_unparseable_python_falls_back_to_sentinel(self) -> None:
        """Conservative: if we can't parse, treat as 'everything changed'."""
        before = "def foo():\n    return 1\n"
        after = "def foo(\n    return 2\n"  # syntax error
        assert _changed_symbols_in_file(before, after) is None

    def test_added_async_function_is_flagged(self) -> None:
        before = ""
        after = "async def foo():\n    return 1\n"
        assert _changed_symbols_in_file(before, after) == {"foo"}


# ---------------------------------------------------------------------------
# Gate-level: combine ADR symbol citations + changed symbols
# ---------------------------------------------------------------------------


def _adr(
    number: int,
    *,
    source_symbols: dict[str, frozenset[str]],
) -> ADR:
    return ADR(
        number=number,
        title=f"Fixture {number}",
        status="Accepted",
        summary="",
        source_files=frozenset(source_symbols.keys()),
        source_symbols=source_symbols,
    )


class TestEvaluateGateWithSymbols:
    """``evaluate_gate`` skips a hit when the cited symbol is unchanged."""

    def test_symbol_qualified_citation_skipped_when_symbol_unchanged(self) -> None:
        adr = _adr(24, source_symbols={"src/agent.py": frozenset({"AgentRunner.run"})})
        hits = {"src/agent.py": [adr]}
        # Author touched src/agent.py but the changed symbol is `__init__`,
        # not `run` — gate should pass.
        changed_symbols = {"src/agent.py": {"AgentRunner.__init__"}}

        passed, unresolved = evaluate_gate(
            changed=["src/agent.py"], hits=hits, changed_symbols=changed_symbols
        )

        assert passed
        assert unresolved == {}

    def test_symbol_qualified_citation_fires_when_symbol_changed(self) -> None:
        adr = _adr(24, source_symbols={"src/agent.py": frozenset({"AgentRunner.run"})})
        hits = {"src/agent.py": [adr]}
        changed_symbols = {"src/agent.py": {"AgentRunner.run"}}

        passed, unresolved = evaluate_gate(
            changed=["src/agent.py"], hits=hits, changed_symbols=changed_symbols
        )

        assert not passed
        assert "src/agent.py" in unresolved

    def test_class_citation_fires_on_method_change(self) -> None:
        """Citing ``ClassName`` fires if any ``ClassName.method`` changed."""
        adr = _adr(24, source_symbols={"src/agent.py": frozenset({"AgentRunner"})})
        hits = {"src/agent.py": [adr]}
        changed_symbols = {"src/agent.py": {"AgentRunner.run"}}

        passed, unresolved = evaluate_gate(
            changed=["src/agent.py"], hits=hits, changed_symbols=changed_symbols
        )

        assert not passed

    def test_bare_citation_fires_on_any_change(self) -> None:
        """Backwards compat: bare citation = any-change-fires."""
        adr = _adr(24, source_symbols={"src/agent.py": frozenset()})
        hits = {"src/agent.py": [adr]}
        # Even an unrelated symbol change fires
        changed_symbols = {"src/agent.py": {"_helper"}}

        passed, unresolved = evaluate_gate(
            changed=["src/agent.py"], hits=hits, changed_symbols=changed_symbols
        )

        assert not passed

    def test_bare_citation_fires_even_with_no_symbol_changes(self) -> None:
        """A pure import/docstring touch on a bare-cited file still fires."""
        adr = _adr(24, source_symbols={"src/agent.py": frozenset()})
        hits = {"src/agent.py": [adr]}
        changed_symbols = {"src/agent.py": set()}  # no symbols changed

        passed, unresolved = evaluate_gate(
            changed=["src/agent.py"], hits=hits, changed_symbols=changed_symbols
        )

        assert not passed

    def test_symbol_citation_skipped_when_only_imports_changed(self) -> None:
        """The headline benefit: pure import cleanup on a symbol-cited
        file no longer trips the gate."""
        adr = _adr(24, source_symbols={"src/agent.py": frozenset({"AgentRunner.run"})})
        hits = {"src/agent.py": [adr]}
        changed_symbols = {"src/agent.py": set()}  # only imports changed

        passed, unresolved = evaluate_gate(
            changed=["src/agent.py"], hits=hits, changed_symbols=changed_symbols
        )

        assert passed

    def test_unparseable_diff_falls_back_to_firing(self) -> None:
        """Sentinel ``None`` from the extractor means 'unknown' → conservative."""
        adr = _adr(24, source_symbols={"src/agent.py": frozenset({"AgentRunner.run"})})
        hits = {"src/agent.py": [adr]}
        changed_symbols = {"src/agent.py": None}  # extractor failed

        passed, unresolved = evaluate_gate(
            changed=["src/agent.py"], hits=hits, changed_symbols=changed_symbols
        )

        assert not passed

    def test_no_changed_symbols_arg_falls_back_to_file_level_behavior(self) -> None:
        """When the caller doesn't supply changed_symbols, behave like today."""
        adr = _adr(24, source_symbols={"src/agent.py": frozenset({"AgentRunner.run"})})
        hits = {"src/agent.py": [adr]}

        passed, unresolved = evaluate_gate(changed=["src/agent.py"], hits=hits)

        assert not passed

    def test_per_adr_resolution_when_one_cites_symbol_and_other_bare(self) -> None:
        """Two ADRs cite the same file — one with symbol, one bare.
        The bare citation alone is enough to fire the gate."""
        adr_symbol = _adr(
            24, source_symbols={"src/agent.py": frozenset({"AgentRunner.run"})}
        )
        adr_bare = _adr(27, source_symbols={"src/agent.py": frozenset()})
        hits = {"src/agent.py": [adr_symbol, adr_bare]}
        changed_symbols = {"src/agent.py": {"AgentRunner.__init__"}}

        passed, unresolved = evaluate_gate(
            changed=["src/agent.py"], hits=hits, changed_symbols=changed_symbols
        )

        # adr_bare keeps firing → gate fails, both ADRs reported as still
        # needing attention (or at least the bare-citing one).
        assert not passed
        assert "src/agent.py" in unresolved

    def test_all_symbol_adrs_skipped_clears_the_gate(self) -> None:
        adr1 = _adr(24, source_symbols={"src/agent.py": frozenset({"X"})})
        adr2 = _adr(27, source_symbols={"src/agent.py": frozenset({"Y"})})
        hits = {"src/agent.py": [adr1, adr2]}
        changed_symbols = {"src/agent.py": {"Z"}}

        passed, unresolved = evaluate_gate(
            changed=["src/agent.py"], hits=hits, changed_symbols=changed_symbols
        )

        assert passed
