from arch.extractors.adr_xref import extract_adr_refs


def test_collision_merges_cited_modules_union(fixture_src_tree):
    root = fixture_src_tree(
        {
            "docs/adr/0064-a.md": "# ADR-0064-a\n\nSee src/foo.py.\n",
            "docs/adr/0064-b.md": "# ADR-0064-b\n\nSee src/bar.py:Bar.\n",
        }
    )
    idx = extract_adr_refs(root / "docs/adr")
    by_id = {r.adr_id: r for r in idx.adr_to_modules}
    assert list(by_id) == ["ADR-0064"], "collision should produce exactly one row"
    mods = by_id["ADR-0064"].cited_modules
    assert "src.foo" in mods
    assert "src.bar" in mods


def test_collision_deduplicates_shared_modules(fixture_src_tree):
    root = fixture_src_tree(
        {
            "docs/adr/0064-a.md": "# ADR-0064-a\n\nSee src/foo.py.\n",
            "docs/adr/0064-b.md": "# ADR-0064-b\n\nAlso src/foo.py here.\n",
        }
    )
    idx = extract_adr_refs(root / "docs/adr")
    by_id = {r.adr_id: r for r in idx.adr_to_modules}
    mods = by_id["ADR-0064"].cited_modules
    assert mods.count("src.foo") == 1, "shared module should appear exactly once"


def test_extracts_module_symbol_and_path_refs(fixture_src_tree):
    root = fixture_src_tree(
        {
            "docs/adr/0001-thing.md": """
            # ADR-0001: Thing

            Reference src/foo.py and another at src/bar.py:Bar.
            See also `src/baz.py:baz_function`.
        """,
            "docs/adr/0002-other.md": "# ADR-0002: Other\n\nNo refs here.\n",
        }
    )
    idx = extract_adr_refs(root / "docs/adr")
    by_id = {r.adr_id: r for r in idx.adr_to_modules}
    assert "ADR-0001" in by_id
    assert "ADR-0002" in by_id
    refs = by_id["ADR-0001"].cited_modules
    assert "src.foo" in refs
    assert "src.bar" in refs
    assert "src.baz" in refs
    assert by_id["ADR-0002"].cited_modules == []


def test_skips_readme_and_template(fixture_src_tree):
    root = fixture_src_tree(
        {
            "docs/adr/README.md": "# Index\n",
            "docs/adr/0001-thing.md": "# ADR-0001\n",
        }
    )
    idx = extract_adr_refs(root / "docs/adr")
    assert [r.adr_id for r in idx.adr_to_modules] == ["ADR-0001"]
