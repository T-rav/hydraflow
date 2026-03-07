"""Tests for RepoStore repo persistence."""

from __future__ import annotations

from pathlib import Path

from repo_store import RepoRecord, RepoStore


def test_upsert_adds_record_and_normalizes_path(tmp_path: Path) -> None:
    store = RepoStore(tmp_path)
    repo_path = tmp_path / "example"
    repo_path.mkdir()

    record = RepoRecord(slug="acme-repo", repo="acme/repo", path=str(repo_path))
    stored = store.upsert(record)

    assert stored.slug == "acme-repo"
    assert Path(stored.path).resolve() == repo_path.resolve()
    listed = store.list()
    assert len(listed) == 1
    assert listed[0].slug == "acme-repo"


def test_upsert_replaces_existing_slug(tmp_path: Path) -> None:
    store = RepoStore(tmp_path)
    first = RepoRecord(slug="acme-repo", repo="acme/repo", path=str(tmp_path / "first"))
    second = RepoRecord(
        slug="acme-repo", repo="acme/repo", path=str(tmp_path / "second")
    )

    store.upsert(first)
    updated = store.upsert(second)

    assert Path(updated.path).name == "second"
    listed = store.list()
    assert len(listed) == 1
    assert Path(listed[0].path).name == "second"


def test_remove_returns_true_when_record_removed(tmp_path: Path) -> None:
    store = RepoStore(tmp_path)
    record = RepoRecord(slug="acme-repo", repo="acme/repo", path=str(tmp_path / "repo"))
    store.upsert(record)

    assert store.remove("acme-repo") is True
    assert store.list() == []
    assert store.remove("missing") is False


def test_get_returns_record_by_slug(tmp_path: Path) -> None:
    store = RepoStore(tmp_path)
    record = RepoRecord(slug="acme-repo", repo="acme/repo", path=str(tmp_path / "repo"))
    store.upsert(record)

    found = store.get("acme-repo")
    assert found is not None
    assert found.slug == "acme-repo"


def test_get_returns_none_for_missing_slug(tmp_path: Path) -> None:
    store = RepoStore(tmp_path)
    assert store.get("nonexistent") is None
    assert store.get("") is None


def test_list_returns_empty_when_file_missing(tmp_path: Path) -> None:
    store = RepoStore(tmp_path)
    assert store.list() == []


def test_list_skips_entries_without_slug_or_path(tmp_path: Path) -> None:
    store = RepoStore(tmp_path)
    import json

    (tmp_path / "repos.json").write_text(
        json.dumps(
            {
                "repos": [
                    {"slug": "", "repo": "a/b", "path": "/some/path"},
                    {"slug": "valid", "repo": "a/b", "path": ""},
                    {"slug": "ok-repo", "repo": "a/b", "path": str(tmp_path)},
                ]
            }
        )
    )
    records = store.list()
    assert len(records) == 1
    assert records[0].slug == "ok-repo"
