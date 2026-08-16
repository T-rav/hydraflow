"""Unit tests for the #11373 wiki compile fingerprint gate."""

from __future__ import annotations

from pathlib import Path

from wiki_compile_state import WikiCompileState, topic_fingerprint


class TestTopicFingerprint:
    def test_stable_across_ordering(self) -> None:
        assert topic_fingerprint([b"a", b"b"]) == topic_fingerprint([b"b", b"a"])

    def test_changes_with_content(self) -> None:
        assert topic_fingerprint([b"a"]) != topic_fingerprint([b"a", b"b"])
        assert topic_fingerprint([b"a"]) != topic_fingerprint([b"c"])

    def test_accepts_str_chunks(self) -> None:
        assert topic_fingerprint(["a"]) == topic_fingerprint([b"a"])


class TestWikiCompileState:
    def test_missing_state_compiles_everything(self, tmp_path: Path) -> None:
        state = WikiCompileState(tmp_path / "nope.json")
        assert state.should_compile("r:t:legacy", "f1") is True

    def test_recorded_fingerprint_skips(self, tmp_path: Path) -> None:
        p = tmp_path / "state.json"
        state = WikiCompileState(p)
        state.record("r:t:legacy", "f1")
        state.save()
        reloaded = WikiCompileState(p)
        assert reloaded.should_compile("r:t:legacy", "f1") is False
        assert reloaded.should_compile("r:t:legacy", "f2") is True

    def test_corrupt_state_fails_open(self, tmp_path: Path) -> None:
        p = tmp_path / "state.json"
        p.write_text("{not json")
        state = WikiCompileState(p)
        assert state.should_compile("k", "f") is True

    def test_non_dict_state_fails_open(self, tmp_path: Path) -> None:
        p = tmp_path / "state.json"
        p.write_text('["a"]')
        assert WikiCompileState(p).should_compile("k", "f") is True
