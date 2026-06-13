"""Unit tests for the conflict-marker guard (scripts/check_conflict_markers.py).

Regression coverage for #9482: raw git conflict markers were committed to 11
wiki-term files (#9422) and no gate rejected them. Markers below are built at
runtime (``"<" * 7``) so this test file never contains a line-start marker that
its own ``--tracked`` scan would flag.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT = Path(__file__).parent.parent / "scripts" / "check_conflict_markers.py"
_spec = importlib.util.spec_from_file_location("check_conflict_markers", _SCRIPT)
assert _spec and _spec.loader
guard = importlib.util.module_from_spec(_spec)
sys.modules["check_conflict_markers"] = guard
_spec.loader.exec_module(guard)

OPEN = "<" * 7
BASE = "|" * 7
SEP = "=" * 7
CLOSE = ">" * 7


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


class TestScan:
    def test_flags_opening_marker(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "f.md",
            f"line one\n{OPEN} HEAD\nmine\n{SEP}\ntheirs\n{CLOSE} branch\n",
        )
        hits = guard.scan(["f.md"], tmp_path)
        assert [(rel, num) for rel, num, _ in hits] == [("f.md", 2), ("f.md", 6)]

    def test_flags_diff3_base_marker(self, tmp_path: Path) -> None:
        _write(
            tmp_path, "f.txt", f"{OPEN} HEAD\na\n{BASE} base\nb\n{SEP}\nc\n{CLOSE} x\n"
        )
        rels = {rel for rel, _, _ in guard.scan(["f.txt"], tmp_path)}
        assert rels == {"f.txt"}
        # all three angle/pipe markers detected (open, base, close)
        assert len(guard.scan(["f.txt"], tmp_path)) == 3

    def test_clean_file_passes(self, tmp_path: Path) -> None:
        _write(tmp_path, "clean.md", "title\nbody text\nmore\n")
        assert guard.scan(["clean.md"], tmp_path) == []

    def test_bare_equals_separator_not_flagged(self, tmp_path: Path) -> None:
        # `=======` is a legitimate Markdown setext heading underline.
        _write(tmp_path, "doc.md", f"My Heading\n{SEP}\n\nbody\n")
        assert guard.scan(["doc.md"], tmp_path) == []

    def test_marker_not_at_line_start_not_flagged(self, tmp_path: Path) -> None:
        _write(tmp_path, "code.py", f'    example = "{OPEN} HEAD"  # documented\n')
        assert guard.scan(["code.py"], tmp_path) == []

    def test_binary_file_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "blob.bin").write_bytes(b"\xff\xfe" + OPEN.encode() + b" \x00\x01")
        assert guard.scan(["blob.bin"], tmp_path) == []

    def test_missing_path_skipped(self, tmp_path: Path) -> None:
        assert guard.scan(["does-not-exist.md"], tmp_path) == []


class TestMain:
    def test_returns_1_when_marker_present(self, tmp_path: Path, monkeypatch) -> None:
        _write(tmp_path, "bad.md", f"{OPEN} HEAD\nx\n{SEP}\ny\n{CLOSE} z\n")
        monkeypatch.setattr(guard, "_repo_root", lambda: tmp_path)
        assert guard.main(["bad.md"]) == 1

    def test_returns_0_when_clean(self, tmp_path: Path, monkeypatch) -> None:
        _write(tmp_path, "ok.md", "all good\n")
        monkeypatch.setattr(guard, "_repo_root", lambda: tmp_path)
        assert guard.main(["ok.md"]) == 0
