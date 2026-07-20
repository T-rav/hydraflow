"""Regression: duplicate UL term files corrupt the store and views (#9938, #9981).

`docs/wiki/terms/fitness-scorecard.md` + `fitness-scorecard-loop.md` (and
`github-cache-loop.md` + `git-hub-cache-loop.md`) each carried the SAME term
id and name: the originals were hand-authored with human-friendly basenames,
but the UL loops (edge-proposer, entry-evidence) write back to
`_slugify_term_name(name)` — so the first loop update forked a second file
and left the stale original behind. The two records then rendered as
duplicate Mermaid node declarations in the context map and double-counted
in the glossary.

Pins (duplicates are a data error, enforced at the store boundary):
- `lint_term_uniqueness` rejects duplicate ids, duplicate names
  (case-insensitive), and any file whose basename is not the canonical slug
  of its `name:` — the exact fork mechanism that minted the duplicates.
- `TermStore.list()` collapses same-id records to the freshest `updated_at`
  (canonical-slug file wins ties), so downstream renderers never
  double-count even if bad data lands on disk.
- The live `docs/wiki/terms/` store passes the uniqueness lint — the
  ULID-uniqueness guard asked for in #9981, mirroring the ADR-number guard.
- The committed context map declares each node id exactly once.
"""

from __future__ import annotations

import re
from pathlib import Path

from ubiquitous_language import (
    BoundedContext,
    Term,
    TermKind,
    TermRel,
    TermRelKind,
    TermStore,
    dump_term_file,
    lint_term_uniqueness,
    render_context_map,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
LIVE_TERMS_DIR = REPO_ROOT / "docs" / "wiki" / "terms"
CONTEXT_MAP_PATH = (
    REPO_ROOT / "docs" / "arch" / "generated" / "ubiquitous-language-context-map.md"
)


def _term(**overrides: object) -> Term:
    defaults: dict[str, object] = {
        "name": "FitnessScorecardLoop",
        "kind": TermKind.LOOP,
        "bounded_context": BoundedContext.CARETAKER,
        "definition": "Read-only caretaker loop producing the fitness scorecard.",
        "code_anchor": "src/fitness_scorecard_loop.py:FitnessScorecardLoop",
    }
    defaults.update(overrides)
    return Term.model_validate(defaults)


class TestLintTermUniqueness:
    def test_flags_two_files_sharing_one_id(self, tmp_path: Path) -> None:
        """The exact #9938/#9981 shape: one term id spread across two files."""
        shared_id = "01JZ9FK3C0M02HYR42BF22W0B2"
        dump_term_file(tmp_path / "fitness-scorecard.md", _term(id=shared_id))
        dump_term_file(tmp_path / "fitness-scorecard-loop.md", _term(id=shared_id))

        failures = lint_term_uniqueness(tmp_path)

        id_failures = [f for f in failures if shared_id in f]
        assert id_failures, failures
        assert "fitness-scorecard.md" in id_failures[0]
        assert "fitness-scorecard-loop.md" in id_failures[0]

    def test_flags_two_distinct_terms_sharing_a_name(self, tmp_path: Path) -> None:
        dump_term_file(
            tmp_path / "git-hub-cache-loop.md", _term(name="GitHubCacheLoop")
        )
        dump_term_file(tmp_path / "github-cache-loop.md", _term(name="GitHubCacheLoop"))

        failures = lint_term_uniqueness(tmp_path)

        assert any(
            "githubcacheloop" in f and "git-hub-cache-loop.md" in f for f in failures
        ), failures

    def test_flags_non_canonical_filename(self, tmp_path: Path) -> None:
        """A basename that is not the slug of `name:` is the fork mechanism:
        the next loop write mints a second file at the canonical slug."""
        dump_term_file(tmp_path / "fitness-scorecard.md", _term())

        failures = lint_term_uniqueness(tmp_path)

        assert len(failures) == 1
        assert "fitness-scorecard.md" in failures[0]
        assert "fitness-scorecard-loop.md" in failures[0]

    def test_clean_canonical_store_passes(self, tmp_path: Path) -> None:
        store = TermStore(tmp_path)
        store.write(_term())
        store.write(
            _term(
                name="GitHubCacheLoop",
                code_anchor="src/github_cache_loop.py:GitHubCacheLoop",
            )
        )

        assert lint_term_uniqueness(tmp_path) == []

    def test_missing_root_is_clean(self, tmp_path: Path) -> None:
        assert lint_term_uniqueness(tmp_path / "absent") == []


class TestTermStoreDuplicateIdCollapse:
    def test_list_keeps_freshest_record_per_id(self, tmp_path: Path) -> None:
        shared_id = "01KR9A3F20M01PGF32CF88W9A2"
        stale = _term(
            id=shared_id,
            name="GitHubCacheLoop",
            definition="stale copy without edges",
            updated_at="2026-05-19T20:00:00+00:00",
        )
        fresh = _term(
            id=shared_id,
            name="GitHubCacheLoop",
            definition="fresh copy with edges",
            updated_at="2026-07-18T19:39:52+00:00",
            related=[
                TermRel(
                    kind=TermRelKind.DEPENDS_ON,
                    target="01KQV37D10M06PGF32CF77W6K5",
                )
            ],
        )
        dump_term_file(tmp_path / "github-cache-loop.md", stale)
        dump_term_file(tmp_path / "git-hub-cache-loop.md", fresh)

        listed = TermStore(tmp_path).list()

        assert len(listed) == 1
        assert listed[0].definition == "fresh copy with edges"
        assert len(listed[0].related) == 1

    def test_list_tie_prefers_canonical_slug_file(self, tmp_path: Path) -> None:
        shared_id = "01KR9A3F20M01PGF32CF88W9A2"
        same_ts = "2026-07-18T19:39:52+00:00"
        dump_term_file(
            tmp_path / "github-cache-loop.md",
            _term(
                id=shared_id,
                name="GitHubCacheLoop",
                definition="non-canonical file",
                updated_at=same_ts,
            ),
        )
        dump_term_file(
            tmp_path / "git-hub-cache-loop.md",
            _term(
                id=shared_id,
                name="GitHubCacheLoop",
                definition="canonical file",
                updated_at=same_ts,
            ),
        )

        listed = TermStore(tmp_path).list()

        assert len(listed) == 1
        assert listed[0].definition == "canonical file"

    def test_distinct_ids_are_not_collapsed(self, tmp_path: Path) -> None:
        store = TermStore(tmp_path)
        store.write(_term())
        store.write(
            _term(
                name="GitHubCacheLoop",
                code_anchor="src/github_cache_loop.py:GitHubCacheLoop",
            )
        )

        assert len(store.list()) == 2


class TestContextMapRendersOneNodePerTerm:
    def test_duplicate_id_files_render_a_single_node_declaration(
        self, tmp_path: Path
    ) -> None:
        shared_id = "01JZ9FK3C0M02HYR42BF22W0B2"
        dump_term_file(
            tmp_path / "fitness-scorecard.md",
            _term(id=shared_id, updated_at="2026-06-30T00:00:00+00:00"),
        )
        dump_term_file(
            tmp_path / "fitness-scorecard-loop.md",
            _term(id=shared_id, updated_at="2026-07-18T19:31:17+00:00"),
        )

        out = render_context_map(TermStore(tmp_path).list())

        declarations = [
            line for line in out.splitlines() if "FitnessScorecardLoop<br/>" in line
        ]
        assert len(declarations) == 1, out


class TestLiveTermStoreIsDuplicateFree:
    def test_live_terms_pass_uniqueness_lint(self) -> None:
        """Guard for #9981: every docs/wiki/terms/*.md has a unique ULID and
        name, and sits at its canonical slug (mirrors the ADR-number guard)."""
        assert lint_term_uniqueness(LIVE_TERMS_DIR) == []

    def test_committed_context_map_declares_each_node_once(self) -> None:
        node_line = re.compile(r"^\s{4}(?P<node>[0-9a-z_]+)\[")
        seen: set[str] = set()
        for line in CONTEXT_MAP_PATH.read_text(encoding="utf-8").splitlines():
            match = node_line.match(line)
            if match is None:
                continue
            node = match.group("node")
            assert node not in seen, f"duplicate node declaration: {node}"
            seen.add(node)
        assert seen, "no node declarations found — regex or artifact drifted"
