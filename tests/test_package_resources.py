# tests/test_package_resources.py
"""Unit tests for the package-aware resource resolver (#11589).

Eight modules used to derive the repo root as
``Path(__file__).resolve().parent.parent`` and read ``prompts/``,
``templates/``, ``static/`` or ``docs/`` from it. That expression names the
checkout's root from ``<repo>/src/mod.py`` and ``lib/python3.11/`` from
``site-packages/mod.py``, so every one of those reads was a silent
wrong-directory lookup in a wheel install. ``package_resources`` replaces the
idiom with two named resolutions — *shipped resource* vs *source checkout* —
each of which either returns a path that exists or raises.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from package_resources import (
    CHECKOUT_ROOT_ENV,
    RESOURCE_PACKAGE,
    RESOURCE_ROOT_ENV,
    RESOURCE_TREES,
    ResourceNotFoundError,
    checkout_path,
    checkout_root,
    find_checkout_root,
    package_root,
    resource_dir,
    resource_path,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _no_ambient_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """The suite must not inherit an operator's override from the environment."""
    monkeypatch.delenv(RESOURCE_ROOT_ENV, raising=False)
    monkeypatch.delenv(CHECKOUT_ROOT_ENV, raising=False)


def _fake_resource_root(tmp_path: Path, tree: str) -> Path:
    root = tmp_path / "override"
    (root / tree).mkdir(parents=True)
    return root


# --- package_root / resource resolution ------------------------------------


def test_package_root_is_the_directory_holding_the_installed_modules() -> None:
    import package_resources

    assert package_root() == Path(package_resources.__file__).resolve().parent


def test_resource_dir_returns_the_tree_shipped_with_the_package() -> None:
    assert resource_dir("prompts") == package_root() / RESOURCE_PACKAGE / "prompts"


def test_resource_dir_only_ever_returns_a_directory_that_exists() -> None:
    assert all(resource_dir(tree).is_dir() for tree in RESOURCE_TREES)


def test_resource_dir_prefers_an_explicit_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _fake_resource_root(tmp_path, "prompts")
    monkeypatch.setenv(RESOURCE_ROOT_ENV, str(root))
    assert resource_dir("prompts") == root / "prompts"


def test_resource_dir_raises_when_the_env_override_lacks_the_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An override that does not hold the resource is an operator error, not a hint."""
    monkeypatch.setenv(RESOURCE_ROOT_ENV, str(tmp_path))
    with pytest.raises(ResourceNotFoundError, match=RESOURCE_ROOT_ENV):
        resource_dir("prompts")


def test_resource_dir_rejects_an_unknown_tree_name() -> None:
    with pytest.raises(ResourceNotFoundError, match="promts"):
        resource_dir("promts")


def test_resource_path_joins_below_the_resource_tree() -> None:
    assert resource_path("prompts", "auto_agent", "_default.md").is_file()


def test_resource_path_raises_when_the_file_is_absent() -> None:
    with pytest.raises(ResourceNotFoundError, match="no-such-prompt.md"):
        resource_path("prompts", "auto_agent", "no-such-prompt.md")


# --- checkout resolution ----------------------------------------------------


def test_checkout_root_finds_the_repo_the_tests_run_from() -> None:
    assert checkout_root() == REPO_ROOT


def test_find_checkout_root_is_none_outside_a_checkout(tmp_path: Path) -> None:
    assert find_checkout_root(tmp_path) is None


def test_find_checkout_root_recognises_the_marker_module(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "package_resources.py").touch()
    assert find_checkout_root(tmp_path / "src") == tmp_path


def test_checkout_root_honours_the_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(CHECKOUT_ROOT_ENV, str(tmp_path))
    assert checkout_root() == tmp_path


def test_checkout_root_raises_when_the_env_override_does_not_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(CHECKOUT_ROOT_ENV, str(tmp_path / "gone"))
    with pytest.raises(ResourceNotFoundError, match=CHECKOUT_ROOT_ENV):
        checkout_root()


def test_checkout_path_resolves_a_file_in_the_checkout() -> None:
    assert checkout_path("pyproject.toml") == REPO_ROOT / "pyproject.toml"


def test_checkout_path_raises_when_the_file_is_missing() -> None:
    with pytest.raises(ResourceNotFoundError, match="not-a-real-file.toml"):
        checkout_path("not-a-real-file.toml")
