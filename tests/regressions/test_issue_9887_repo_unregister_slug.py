"""Regression: idle repos could never be unregistered (#9887).

``/api/repos`` renders a path-sanitized slug (``owner/name`` →
``owner-name``) for the DELETE URL, but ``repo_store.remove`` matched only
the RAW record slug — so the exact slug the listing emitted always 404'd
and idle registrations were stuck in the UI forever.

Pins: removal accepts both forms; ``resolve_slug`` maps a sanitized slug
back to the raw registry key; misses stay misses.
"""

from __future__ import annotations

from pathlib import Path

from repo_store import RepoRecord, RepoStore


def _store_with(tmp_path: Path, slug: str) -> RepoStore:
    store = RepoStore(tmp_path / "repos.json")
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir(exist_ok=True)
    store.upsert(RepoRecord(slug=slug, repo="T-rav/amplifier", path=str(repo_dir)))
    return store


def test_remove_accepts_the_sanitized_slug_the_listing_emits(tmp_path: Path) -> None:
    store = _store_with(tmp_path, "T-rav/amplifier")

    assert store.remove("T-rav-amplifier") is True  # the exact UI DELETE value
    assert store.list() == []


def test_remove_still_accepts_the_raw_slug(tmp_path: Path) -> None:
    store = _store_with(tmp_path, "T-rav/amplifier")

    assert store.remove("T-rav/amplifier") is True
    assert store.list() == []


def test_resolve_slug_maps_sanitized_to_raw_registry_key(tmp_path: Path) -> None:
    store = _store_with(tmp_path, "T-rav/amplifier")

    assert store.resolve_slug("T-rav-amplifier") == "T-rav/amplifier"
    assert store.resolve_slug("T-rav/amplifier") == "T-rav/amplifier"
    assert store.resolve_slug("nope") is None
    assert store.resolve_slug("  ") is None


def test_miss_still_returns_false(tmp_path: Path) -> None:
    store = _store_with(tmp_path, "T-rav/amplifier")

    assert store.remove("other-repo") is False
    assert len(store.list()) == 1
