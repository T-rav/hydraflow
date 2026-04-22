"""Integration tests: tree_sitter_extractor against vendored real-world snapshots.

Each test case runs the extractor for one language against a small (~20 file,
<50 KB) vendored fixture and checks:

  1. No crash — extractor returns without raising.
  2. Non-zero graph — at least ``min_nodes`` nodes are produced.
  3. Expected edges — every edge in ``expected_edges`` appears in the graph.
  4. No forbidden edges — edges pointing at LICENSE/README/non-source files are
     absent.

See ``tests/arch/fixtures/real_world/ATTRIBUTION.md`` for repo provenance,
commit SHAs, and per-language extractor findings/limitations.

Known limitations:
- JavaScript: CommonJS ``require(...)`` is not captured — only ESM ``import``.
  No repo under test relies on CJS for internal deps.
- Swift: not supported; the bundled ``tree_sitter_languages`` does not include
  a Swift grammar. Adding one requires a separate ``tree-sitter-swift`` dep
  and is tracked as a follow-up.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arch.tree_sitter import tree_sitter_extractor

REAL_WORLD = Path(__file__).parent / "fixtures" / "real_world"

# ---------------------------------------------------------------------------
# Per-language test data
# ---------------------------------------------------------------------------
# (language, fixture_subdir, min_nodes, expected_edges, forbidden_edges)
#
# expected_edges: edges we KNOW must appear from reading the vendored source.
# forbidden_edges: edges that would indicate false positives (e.g., a source
#   file "importing" a LICENSE or README).
#
# Languages where the extractor produces zero edges (Python, Go, Java, Rust)
# use expected_edges=set() because asserting absent edges would make the test
# always fail. The limitations are documented in ATTRIBUTION.md.

CASES: list[tuple[str, str, int, set[tuple[str, str]], set[tuple[str, str]]]] = [
    # --- Python: python-dotenv ---
    # Relative imports (`from .main import foo`) resolve to the sibling file.
    (
        "python",
        "python",
        4,
        {
            ("src/dotenv/__init__.py", "src/dotenv/main.py"),
            ("src/dotenv/main.py", "src/dotenv/parser.py"),
            ("src/dotenv/main.py", "src/dotenv/variables.py"),
        },
        {
            ("src/dotenv/__init__.py", "LICENSE"),
            ("src/dotenv/main.py", "LICENSE"),
        },
    ),
    # --- TypeScript: neverthrow ---
    # Relative imports like `import { ... } from './result'` resolve correctly.
    (
        "typescript",
        "typescript",
        5,
        {
            ("src/result.ts", "src/_internals/error.ts"),
            ("src/result-async.ts", "src/result.ts"),
        },
        {
            ("src/index.ts", "LICENSE"),
            ("src/result.ts", "LICENSE"),
        },
    ),
    # --- JavaScript: execa lib/arguments subset ---
    # ESM `import` statements with relative paths resolve correctly.
    (
        "javascript",
        "javascript",
        9,
        {
            ("lib/arguments/options.js", "lib/arguments/cwd.js"),
            ("lib/arguments/command.js", "lib/arguments/escape.js"),
        },
        {
            ("lib/arguments/options.js", "LICENSE"),
            ("lib/arguments/command.js", "LICENSE"),
        },
    ),
    # --- Go: synthesized two-package groupcache-inspired example ---
    # ``cache`` package imports ``lru`` package via a grouped ``import (...)``
    # block. The directory-unit extractor maps each package dir to a node; the
    # stems map includes f.parent.name so "lru" resolves to the lru/ directory
    # node. The query matches ``import_spec`` at any depth so both grouped and
    # single-line imports are captured.
    (
        "go",
        "go_multi",
        2,
        {("cache", "lru")},
        {
            ("cache", "LICENSE"),
            ("lru", "LICENSE"),
            ("cache", "go.mod"),
        },
    ),
    # --- Java: synthesized 3-class example ---
    # Scoped identifiers (`import com.example.result.Success`) resolve via
    # last-segment stem lookup to the corresponding source file.
    (
        "java",
        "java",
        3,
        {
            (
                "src/main/java/com/example/result/Result.java",
                "src/main/java/com/example/result/Success.java",
            ),
            (
                "src/main/java/com/example/result/Result.java",
                "src/main/java/com/example/result/Failure.java",
            ),
        },
        {
            (
                "src/main/java/com/example/result/Result.java",
                "LICENSE",
            ),
        },
    ),
    # --- Rust: itoa ---
    # `mod u128_ext;` in lib.rs is a mod_item; the query captures its name
    # identifier and resolves to the sibling u128_ext.rs file.
    (
        "rust",
        "rust",
        2,
        {("src/lib.rs", "src/u128_ext.rs")},
        {
            ("src/lib.rs", "LICENSE"),
            ("src/lib.rs", "Cargo.toml"),
        },
    ),
    # --- Ruby: rake lib subset ---
    # `require_relative` calls resolve via stem lookup.
    (
        "ruby",
        "ruby",
        6,
        {
            ("lib/rake/task.rb", "lib/rake/invocation_exception_mixin.rb"),
            ("lib/rake.rb", "lib/rake/version.rb"),
        },
        {
            ("lib/rake.rb", "LICENSE"),
            ("lib/rake/version.rb", "LICENSE"),
        },
    ),
    # --- C#: synthesized 4-class result-type example ---
    # `using Example.Result.Success;` → stem "Success" → Success.cs.
    # The query captures the qualified_name child of using_directive; the stem
    # key uses rsplit(".", 1)[-1] to extract the class name.
    (
        "csharp",
        "csharp",
        4,
        {
            (
                "src/Result/ResultFactory.cs",
                "src/Result/Success.cs",
            ),
            (
                "src/Result/ResultFactory.cs",
                "src/Result/Failure.cs",
            ),
            (
                "src/Result/Success.cs",
                "src/Result/IResult.cs",
            ),
        },
        {
            ("src/Result/ResultFactory.cs", "LICENSE"),
            ("src/Result/Success.cs", "LICENSE"),
        },
    ),
    # --- Kotlin: synthesized 4-class result-type example ---
    # `import com.example.result.Success` → stem "Success" → Success.kt.
    # The identifier node inside import_header holds the full dotted path;
    # rsplit(".", 1)[-1] extracts the class name for stem lookup.
    (
        "kotlin",
        "kotlin",
        4,
        {
            (
                "src/main/kotlin/com/example/result/ResultFactory.kt",
                "src/main/kotlin/com/example/result/Success.kt",
            ),
            (
                "src/main/kotlin/com/example/result/ResultFactory.kt",
                "src/main/kotlin/com/example/result/Failure.kt",
            ),
            (
                "src/main/kotlin/com/example/result/Success.kt",
                "src/main/kotlin/com/example/result/IResult.kt",
            ),
        },
        {
            (
                "src/main/kotlin/com/example/result/ResultFactory.kt",
                "LICENSE",
            ),
        },
    ),
    # --- PHP: synthesized 4-class result-type example ---
    # `use Example\Result\Success;` → stem "Success" → Success.php.
    # The qualified_name child of namespace_use_clause holds the backslash-
    # separated path; rsplit("\\", 1)[-1] extracts the class name.
    # Bare class names (e.g. `use DateTime;`) produce a `name` node, not a
    # qualified_name, so they are correctly excluded.
    (
        "php",
        "php",
        4,
        {
            (
                "src/Result/ResultFactory.php",
                "src/Result/Success.php",
            ),
            (
                "src/Result/ResultFactory.php",
                "src/Result/Failure.php",
            ),
            (
                "src/Result/Success.php",
                "src/Result/IResult.php",
            ),
        },
        {
            ("src/Result/ResultFactory.php", "LICENSE"),
            ("src/Result/Success.php", "LICENSE"),
        },
    ),
]


@pytest.mark.parametrize(
    "lang,subdir,min_nodes,expected,forbidden",
    CASES,
    ids=[c[0] for c in CASES],
)
def test_real_world_extractor_smoke(
    lang: str,
    subdir: str,
    min_nodes: int,
    expected: set[tuple[str, str]],
    forbidden: set[tuple[str, str]],
) -> None:
    """Extractor returns a plausible graph for a vendored real-world snapshot."""
    fixture_dir = REAL_WORLD / subdir
    assert fixture_dir.is_dir(), f"fixture dir missing: {fixture_dir}"

    extract = tree_sitter_extractor(lang)
    graph = extract(str(fixture_dir))

    # 1. Non-zero graph
    assert len(graph.nodes) >= min_nodes, (
        f"{lang}: expected >= {min_nodes} nodes, got {len(graph.nodes)}: {sorted(graph.nodes)}"
    )

    # 2. At least the expected edges are present
    missing = expected - graph.edges
    assert not missing, (
        f"{lang}: missing expected edges: {missing}\n"
        f"  actual edges: {sorted(graph.edges)}"
    )

    # 3. No forbidden edges
    bad = forbidden & graph.edges
    assert not bad, (
        f"{lang}: forbidden edges present: {bad}\n"
        f"  full edge set: {sorted(graph.edges)}"
    )
