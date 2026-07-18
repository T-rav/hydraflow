"""Tests for arch.generators.traceability_matrix (CH-5, #9733).

Synthetic requirement IDs below live only in string literals and synthetic
tmp_path fixtures — never in THIS file's docstrings — so they cannot leak
into the live generated matrix as test evidence.
"""

from __future__ import annotations

from pathlib import Path

from arch._models import TraceCommitInfo
from arch.generators.traceability_matrix import (
    parse_trace_commits,
    render_traceability_matrix,
)

# ---------------------------------------------------------------------------
# parse_trace_commits — git log (%H\x1f%s\x1f%B\x1e records) → TraceCommitInfo
# ---------------------------------------------------------------------------


def _record(sha: str, subject: str, body: str) -> str:
    return f"{sha}\x1f{subject}\x1f{body}\x1e"


class TestParseTraceCommits:
    def test_squash_commit_with_trailer_parsed(self) -> None:
        raw = _record(
            "a" * 40,
            "feat(x): traced change (#9001)",
            "feat(x): traced change (#9001)\n\nCloses #42.\n\nReq-ID: REQ-042",
        )
        commits = parse_trace_commits(raw)
        assert len(commits) == 1
        commit = commits[0]
        assert commit.pr_number == 9001
        assert commit.req_ids == ["REQ-042"]
        assert commit.issue_refs == [42]

    def test_non_pr_commits_excluded_from_population(self) -> None:
        raw = _record("b" * 40, "wip: local work", "wip: local work")
        assert parse_trace_commits(raw) == []

    def test_bullet_mangled_trailer_still_found(self) -> None:
        # GitHub squash merges concatenate branch commit messages as bullets,
        # which breaks strict git-trailer parsing; the scan must survive it.
        raw = _record(
            "c" * 40,
            "feat(y): squashed (#9002)",
            "* feat(y): part one\n\n* Req-ID: SYS-9\n\n* feat(y): part two",
        )
        commits = parse_trace_commits(raw)
        assert commits[0].req_ids == ["SYS-9"]

    def test_untraced_pr_commit_has_empty_req_ids(self) -> None:
        raw = _record("d" * 40, "feat(z): plain (#9003)", "feat(z): plain (#9003)")
        commits = parse_trace_commits(raw)
        assert commits[0].req_ids == []

    def test_mid_line_prose_mention_is_not_a_requirement(self) -> None:
        # Trailers are line-initial; a prose sentence that happens to contain
        # the key mid-line (e.g. commit messages ABOUT the threading feature)
        # must not mint a requirement ID.
        raw = _record(
            "9" * 40,
            "feat(docs): explain threading (#9005)",
            "Optional req:<id> label / Req-ID: body-field parsing improved.",
        )
        commits = parse_trace_commits(raw)
        assert commits[0].req_ids == []

    def test_approval_trailers_collected(self) -> None:
        raw = _record(
            "e" * 40,
            "feat(w): approved (#9004)",
            "body\n\nReviewed-by: Alice <a@x>\nApproved-by: Bob <b@x>",
        )
        commits = parse_trace_commits(raw)
        assert commits[0].approvals == ["Alice <a@x>", "Bob <b@x>"]

    def test_window_caps_population(self) -> None:
        raw = "".join(
            _record(f"{i:040d}", f"feat: n{i} (#{i})", f"feat: n{i} (#{i})")
            for i in range(1, 601)
        )
        commits = parse_trace_commits(raw, window=500)
        assert len(commits) == 500
        assert commits[0].pr_number == 1  # newest-first order preserved

    def test_malformed_records_skipped(self) -> None:
        assert parse_trace_commits("garbage-without-separators") == []
        assert parse_trace_commits("") == []


# ---------------------------------------------------------------------------
# render_traceability_matrix
# ---------------------------------------------------------------------------


def _traced_commit(**overrides: object) -> TraceCommitInfo:
    defaults: dict[str, object] = {
        "sha": "f" * 40,
        "subject": "feat(x): traced (#9001)",
        "pr_number": 9001,
        "req_ids": ["REQ-042"],
        "issue_refs": [42],
        "approvals": ["Alice <a@x>"],
    }
    defaults.update(overrides)
    return TraceCommitInfo(**defaults)  # type: ignore[arg-type]


class TestRenderTraceabilityMatrix:
    def test_empty_inputs_render_placeholder_and_zero_pct(self, tmp_path: Path) -> None:
        md = render_traceability_matrix([], repo_root=tmp_path)
        assert "# Requirements Traceability Matrix" in md
        assert "no requirement IDs threaded yet" in md
        assert "<!-- untraced-pct: 0 -->" in md
        assert "{{ARCH_FOOTER}}" in md
        assert "do not hand-edit" in md

    def test_traced_commit_produces_full_row(self, tmp_path: Path) -> None:
        md = render_traceability_matrix([_traced_commit()], repo_root=tmp_path)
        row = next(line for line in md.splitlines() if line.startswith("| REQ-042"))
        assert "#42" in row
        assert "#9001" in row
        assert f"`{'f' * 7}`" in row
        assert "Alice" in row
        assert "<!-- untraced-pct: 0 -->" in md

    def test_untraced_fraction_is_ceiled_percentage(self, tmp_path: Path) -> None:
        commits = [_traced_commit()] + [
            _traced_commit(sha=str(i) * 40, pr_number=i, req_ids=[], issue_refs=[])
            for i in range(1, 7)
        ]
        # 6 of 7 untraced → ceil(600/7) = 86
        md = render_traceability_matrix(commits, repo_root=tmp_path)
        assert "<!-- untraced-pct: 86 -->" in md
        assert "(untraced)" in md
        assert "86%" in md

    def test_all_untraced_pins_at_100(self, tmp_path: Path) -> None:
        commits = [
            _traced_commit(sha=str(i) * 40, pr_number=i, req_ids=[], issue_refs=[])
            for i in range(1, 4)
        ]
        md = render_traceability_matrix(commits, repo_root=tmp_path)
        assert "<!-- untraced-pct: 100 -->" in md

    def test_test_docstring_evidence_joins_matrix(self, tmp_path: Path) -> None:
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_widget.py").write_text(
            '"""Verifies Req-ID: REQ-042 end-to-end."""\n\n'
            "def test_widget() -> None:\n"
            '    """Covers Req-ID: REQ-777."""\n'
            "    assert True\n"
        )
        md = render_traceability_matrix([_traced_commit()], repo_root=tmp_path)
        req_row = next(line for line in md.splitlines() if line.startswith("| REQ-042"))
        assert "tests/test_widget.py" in req_row
        # Test-only requirement still gets a row (with no commits/PRs).
        assert any(line.startswith("| REQ-777") for line in md.splitlines())

    def test_req_id_in_code_string_is_not_evidence(self, tmp_path: Path) -> None:
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_other.py").write_text(
            "def test_other() -> None:\n"
            '    payload = "Req-ID: REQ-042"\n'
            "    assert payload\n"
        )
        md = render_traceability_matrix([_traced_commit()], repo_root=tmp_path)
        req_row = next(line for line in md.splitlines() if line.startswith("| REQ-042"))
        assert "tests/test_other.py" not in req_row

    def test_render_is_deterministic(self, tmp_path: Path) -> None:
        commits = [
            _traced_commit(),
            _traced_commit(sha="0" * 40, pr_number=2, req_ids=[], issue_refs=[]),
        ]
        first = render_traceability_matrix(commits, repo_root=tmp_path)
        second = render_traceability_matrix(commits, repo_root=tmp_path)
        assert first == second

    def test_untraced_section_omits_raw_counts(self, tmp_path: Path) -> None:
        # Raw commit counts would change on every merge and churn drift-CI;
        # only the integer percentage may appear.
        commits = [
            _traced_commit(sha=str(i) * 40, pr_number=i, req_ids=[], issue_refs=[])
            for i in range(1, 8)
        ]
        md = render_traceability_matrix(commits, repo_root=tmp_path)
        untraced_section = md.split("## Section 2")[1]
        assert "7" not in untraced_section.replace("untraced-pct: 100", "")
