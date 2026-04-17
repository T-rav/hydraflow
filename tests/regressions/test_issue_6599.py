"""Regression test for issue #6599.

RepoWikiStore performs several write_text() calls without try/except.
An OSError (disk full, permission denied) propagates out of the public
API methods and can corrupt the wiki mid-write (partial index with stale
topics, or vice-versa).

These tests verify the DESIRED behavior: public methods should handle
write failures gracefully -- catch OSError, log a warning, and return
a valid (possibly partial) result instead of crashing the caller.

All tests are RED until the write_text calls are wrapped in
try/except OSError.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from repo_wiki import DEFAULT_TOPICS, RepoWikiStore, WikiEntry

REPO = "acme/widget"


def _make_entry(title: str = "Test insight", **kwargs) -> WikiEntry:
    defaults = {
        "content": "Some useful knowledge.",
        "source_type": "plan",
        "source_issue": 42,
    }
    defaults.update(kwargs)
    return WikiEntry(title=title, **defaults)


def _seed_wiki(store: RepoWikiStore) -> None:
    """Ingest an initial entry so the wiki directory and files exist."""
    store.ingest(
        REPO,
        [_make_entry(title="Seed entry about gotcha pitfalls and edge cases")],
    )


def _write_text_raiser(*, fail_on: set[str]):
    """Return a replacement for Path.write_text that raises OSError
    when the file's name matches any entry in *fail_on*."""
    original = Path.write_text

    def _patched(self_path: Path, *args, **kwargs):
        if self_path.name in fail_on:
            raise OSError(f"Simulated disk-full writing {self_path.name}")
        return original(self_path, *args, **kwargs)

    return _patched


# -------------------------------------------------------------------
# ingest() propagates OSError
# -------------------------------------------------------------------


class TestIngestWriteFailure:
    """Issue #6599: ingest() should not propagate OSError from write_text."""

    @pytest.mark.xfail(reason="Regression for issue #6599 — fix not yet landed", strict=False)
    def test_topic_write_failure_does_not_crash_ingest(self, tmp_path: Path) -> None:
        """_write_topic_page (line 560) raises OSError during ingest.

        BUG: the exception propagates out of ingest(), killing the
        calling loop instead of being caught and logged.
        """
        store = RepoWikiStore(tmp_path / "wiki")
        _seed_wiki(store)

        entry = _make_entry(title="New gotcha about edge case pitfalls")
        topic = store._classify_topic(entry)
        topic_file = f"{topic}.md"

        raiser = _write_text_raiser(fail_on={topic_file})

        try:
            with patch.object(Path, "write_text", new=raiser):
                store.ingest(REPO, [entry])
        except OSError as exc:
            pytest.fail(
                f"ingest() propagated OSError instead of handling it: {exc} (line 560)"
            )

    @pytest.mark.xfail(reason="Regression for issue #6599 — fix not yet landed", strict=False)
    def test_index_json_write_failure_does_not_crash_ingest(
        self, tmp_path: Path
    ) -> None:
        """_rebuild_index (line 604) raises OSError writing index.json.

        BUG: the exception propagates out of ingest().
        """
        store = RepoWikiStore(tmp_path / "wiki")
        _seed_wiki(store)

        raiser = _write_text_raiser(fail_on={"index.json"})

        try:
            with patch.object(Path, "write_text", new=raiser):
                store.ingest(
                    REPO,
                    [_make_entry(title="Another insight about testing")],
                )
        except OSError as exc:
            pytest.fail(
                f"ingest() propagated OSError from _rebuild_index: {exc} (line 604)"
            )

    @pytest.mark.xfail(reason="Regression for issue #6599 — fix not yet landed", strict=False)
    def test_index_md_write_failure_does_not_crash_ingest(self, tmp_path: Path) -> None:
        """_rebuild_index (line 616) raises OSError writing index.md.

        BUG: index.json write (line 604) succeeds but index.md write
        fails, and the error propagates out of ingest().
        """
        store = RepoWikiStore(tmp_path / "wiki")
        _seed_wiki(store)

        raiser = _write_text_raiser(fail_on={"index.md"})

        try:
            with patch.object(Path, "write_text", new=raiser):
                store.ingest(
                    REPO,
                    [_make_entry(title="Entry that triggers rebuild about testing")],
                )
        except OSError as exc:
            pytest.fail(
                f"ingest() propagated OSError from index.md write: {exc} (line 616)"
            )


# -------------------------------------------------------------------
# active_lint() propagates OSError
# -------------------------------------------------------------------


class TestActiveLintWriteFailure:
    """Issue #6599: active_lint() should not propagate OSError."""

    @pytest.mark.xfail(reason="Regression for issue #6599 — fix not yet landed", strict=False)
    def test_last_lint_index_write_failure_does_not_crash(self, tmp_path: Path) -> None:
        """index_path.write_text at line 373 raises OSError.

        BUG: the exception propagates out of active_lint(), killing
        the RepoWikiLoop iteration.
        """
        store = RepoWikiStore(tmp_path / "wiki")
        _seed_wiki(store)

        raiser = _write_text_raiser(fail_on={"index.json"})

        try:
            with patch.object(Path, "write_text", new=raiser):
                store.active_lint(REPO, closed_issues={42})
        except OSError as exc:
            pytest.fail(
                f"active_lint() propagated OSError from last_lint write: "
                f"{exc} (line 373)"
            )

    @pytest.mark.xfail(reason="Regression for issue #6599 — fix not yet landed", strict=False)
    def test_topic_write_failure_during_stale_marking_does_not_crash(
        self, tmp_path: Path
    ) -> None:
        """_write_topic_page called at line 361 raises OSError when
        active_lint modifies a topic (marking entries stale).

        BUG: the exception propagates out of active_lint().
        """
        store = RepoWikiStore(tmp_path / "wiki")
        store.ingest(
            REPO,
            [
                _make_entry(
                    title="Insight from closed gotcha issue",
                    source_issue=99,
                ),
            ],
        )

        entry = _make_entry(title="Insight from closed gotcha issue")
        topic = store._classify_topic(entry)
        topic_file = f"{topic}.md"

        raiser = _write_text_raiser(fail_on={topic_file})

        try:
            with patch.object(Path, "write_text", new=raiser):
                store.active_lint(REPO, closed_issues={99})
        except OSError as exc:
            pytest.fail(
                f"active_lint() propagated OSError from topic write: "
                f"{exc} (line 361 -> 560)"
            )


# -------------------------------------------------------------------
# _ensure_repo_dir() propagates OSError
# -------------------------------------------------------------------


class TestEnsureRepoDirWriteFailure:
    """Issue #6599: _ensure_repo_dir should not propagate OSError."""

    @pytest.mark.xfail(reason="Regression for issue #6599 — fix not yet landed", strict=False)
    def test_topic_file_seeding_failure_does_not_crash(self, tmp_path: Path) -> None:
        """write_text at line 431 raises OSError during topic file seeding.

        BUG: the exception propagates, preventing the repo directory
        from being initialized.
        """
        store = RepoWikiStore(tmp_path / "wiki")

        topic_files = {f"{t}.md" for t in DEFAULT_TOPICS}
        raiser = _write_text_raiser(fail_on=topic_files)

        try:
            with patch.object(Path, "write_text", new=raiser):
                store._ensure_repo_dir(REPO)
        except OSError as exc:
            pytest.fail(
                f"_ensure_repo_dir() propagated OSError during topic "
                f"seeding: {exc} (line 431)"
            )

    @pytest.mark.xfail(reason="Regression for issue #6599 — fix not yet landed", strict=False)
    def test_index_seeding_failure_does_not_crash(self, tmp_path: Path) -> None:
        """write_text at line 439 raises OSError during index.json seeding.

        BUG: the exception propagates, preventing the repo directory
        from being initialized.
        """
        store = RepoWikiStore(tmp_path / "wiki")

        raiser = _write_text_raiser(fail_on={"index.json"})

        try:
            with patch.object(Path, "write_text", new=raiser):
                store._ensure_repo_dir(REPO)
        except OSError as exc:
            pytest.fail(
                f"_ensure_repo_dir() propagated OSError during index "
                f"seeding: {exc} (line 439)"
            )
