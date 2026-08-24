"""Unit tests for the audit's layout-aware source resolver (#11709).

The audit used to spell every source probe as a flat literal
``ctx.root / "src" / "<name>.py"``.  The greenfield kernel writer stamps
``src/<pkg>/``, so on every repo it creates the probe missed and the check
returned ``FAIL: src/ports.py missing`` — the thing the check exists to assess
was never assessed.  These tests pin the resolver that replaced those literals:
what counts as a root package, and which candidate wins.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.hydraflow_audit import layout
from scripts.hydraflow_audit.models import CheckContext


def _write(root: Path, rel: str, body: str = "") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


# --- root_packages: discovery -------------------------------------------


def test_flat_repo_has_no_root_packages(tmp_path: Path) -> None:
    _write(tmp_path, "src/ports.py", "x = 1\n")

    assert layout.root_packages(tmp_path) == ()


def test_packaged_repo_is_discovered_from_project_name(tmp_path: Path) -> None:
    _write(tmp_path, "src/memoiq/__init__.py")
    _write(tmp_path, "pyproject.toml", '[project]\nname = "memoiq"\n')

    assert layout.root_packages(tmp_path) == ("memoiq",)


def test_project_name_is_normalised_to_an_import_identifier(tmp_path: Path) -> None:
    """``KernelSpec.pkg`` lowercases and dash-to-underscores ``project.name``."""
    _write(tmp_path, "src/my_app/__init__.py")
    _write(tmp_path, "pyproject.toml", '[project]\nname = "My-App"\n')

    assert layout.root_packages(tmp_path) == ("my_app",)


def test_declared_package_absent_on_disk_is_dropped(tmp_path: Path) -> None:
    """HydraFlow declares ``name = "hydraflow"`` but has no ``src/hydraflow/``."""
    _write(tmp_path, "src/ports.py", "x = 1\n")
    _write(tmp_path, "pyproject.toml", '[project]\nname = "hydraflow"\n')

    assert layout.root_packages(tmp_path) == ()


def test_filesystem_fallback_finds_the_lone_package(tmp_path: Path) -> None:
    """No pyproject at all — the single ``src/*/`` package is the root."""
    _write(tmp_path, "src/weird_pkg/__init__.py")

    assert layout.root_packages(tmp_path) == ("weird_pkg",)


def test_sub_packages_of_a_flat_repo_are_not_roots(tmp_path: Path) -> None:
    """The HydraFlow shape: flat modules *and* package directories under src/.

    ``src/hydraflow_gateway/`` is a sub-package of a flat repo. Treating it as
    a root would repoint every probe in this repo at a path under it.
    """
    _write(tmp_path, "src/ports.py", "x = 1\n")
    _write(tmp_path, "src/hydraflow_gateway/__init__.py")
    _write(tmp_path, "src/mockworld/__init__.py")

    assert layout.root_packages(tmp_path) == ()


def test_directory_without_init_is_not_a_package(tmp_path: Path) -> None:
    _write(tmp_path, "src/static/style.css", "body {}")

    assert layout.root_packages(tmp_path) == ()


def test_multiple_packages_are_all_probed_in_sorted_order(tmp_path: Path) -> None:
    """Ambiguity is resolved by what is on disk, not by refusing to look."""
    _write(tmp_path, "src/bpkg/__init__.py")
    _write(tmp_path, "src/apkg/__init__.py")

    assert layout.root_packages(tmp_path) == ("apkg", "bpkg")


def test_declared_package_wins_over_the_filesystem_ordering(tmp_path: Path) -> None:
    _write(tmp_path, "src/bpkg/__init__.py")
    _write(tmp_path, "src/apkg/__init__.py")
    _write(tmp_path, "pyproject.toml", '[project]\nname = "bpkg"\n')

    assert layout.root_packages(tmp_path) == ("bpkg",)


def test_missing_src_directory_yields_no_packages(tmp_path: Path) -> None:
    assert layout.root_packages(tmp_path) == ()


def test_unparseable_pyproject_falls_back_to_the_filesystem(tmp_path: Path) -> None:
    _write(tmp_path, "src/memoiq/__init__.py")
    _write(tmp_path, "pyproject.toml", "this is not = [ valid toml\n")

    assert layout.root_packages(tmp_path) == ("memoiq",)


_BUILD_BACKENDS = [
    pytest.param(
        '[tool.hatch.build.targets.wheel]\npackages = ["src/memoiq"]\n', id="hatch"
    ),
    pytest.param(
        '[tool.poetry]\npackages = [{include = "memoiq", from = "src"}]\n', id="poetry"
    ),
    pytest.param(
        '[tool.setuptools]\npackages = ["memoiq", "memoiq.sub"]\n', id="setuptools-list"
    ),
    pytest.param(
        '[tool.setuptools.packages.find]\ninclude = ["memoiq*"]\n',
        id="setuptools-find-include",
    ),
    pytest.param(
        '[tool.setuptools]\npackage-dir = {memoiq = "src/memoiq"}\n',
        id="setuptools-package-dir",
    ),
]


@pytest.mark.parametrize("pyproject", _BUILD_BACKENDS)
def test_every_supported_build_backend_declares_the_package(
    tmp_path: Path, pyproject: str
) -> None:
    _write(tmp_path, "src/memoiq/__init__.py")
    _write(tmp_path, "pyproject.toml", pyproject)

    assert layout.root_packages(tmp_path) == ("memoiq",)


def test_project_scripts_is_not_a_discovery_source(tmp_path: Path) -> None:
    """HydraFlow's own ``hydraflow-gateway = "hydraflow_gateway...."`` entry.

    Reading entry points would nominate a *sub*-package of a flat repo as its
    root, and every missing-module message here would name a path under it.
    """
    _write(tmp_path, "src/ports.py", "x = 1\n")
    _write(tmp_path, "src/hydraflow_gateway/__init__.py")
    _write(
        tmp_path,
        "pyproject.toml",
        '[project]\nname = "hydraflow"\n\n'
        '[project.scripts]\nhf-gw = "hydraflow_gateway.__main__:main"\n',
    )

    assert layout.root_packages(tmp_path) == ()


def test_setuptools_package_dir_src_root_form_names_nothing(tmp_path: Path) -> None:
    """``package-dir = {"" = "src"}`` says *where*, not *what*."""
    _write(tmp_path, "src/ports.py", "x = 1\n")
    _write(
        tmp_path,
        "pyproject.toml",
        '[tool.setuptools]\npackage-dir = {"" = "src"}\n',
    )

    assert layout.root_packages(tmp_path) == ()


# --- src_module / src_dir: resolution ------------------------------------


def test_src_module_resolves_the_flat_path(tmp_path: Path) -> None:
    expected = _write(tmp_path, "src/ports.py", "x = 1\n")

    assert layout.src_module(tmp_path, "ports") == expected


def test_src_module_resolves_the_packaged_path(tmp_path: Path) -> None:
    _write(tmp_path, "src/memoiq/__init__.py")
    expected = _write(tmp_path, "src/memoiq/ports.py", "x = 1\n")

    assert layout.src_module(tmp_path, "ports") == expected


def test_flat_wins_when_both_layouts_hold_the_module(tmp_path: Path) -> None:
    """Documented precedence: the unambiguous path wins.

    Determinism, and no behaviour change for any flat repo the audit already
    runs against. A repo holding both is mid-migration; resolving to the flat
    copy can be *wrong*, but the check reports the path it probed, so it is
    never *silent* — which is the failure mode being fixed.
    """
    flat = _write(tmp_path, "src/ports.py", "flat\n")
    _write(tmp_path, "src/memoiq/__init__.py")
    _write(tmp_path, "src/memoiq/ports.py", "packaged\n")

    assert layout.src_module(tmp_path, "ports") == flat


def test_absent_module_names_the_packaged_path_on_a_packaged_repo(
    tmp_path: Path,
) -> None:
    """The ``... missing`` message must name a path this repo would use."""
    _write(tmp_path, "src/memoiq/__init__.py")

    resolved = layout.src_module(tmp_path, "ports")

    assert resolved == tmp_path / "src" / "memoiq" / "ports.py"
    assert not resolved.exists()


def test_absent_module_names_the_flat_path_on_a_flat_repo(tmp_path: Path) -> None:
    _write(tmp_path, "src/config.py", "x = 1\n")

    assert layout.src_module(tmp_path, "ports") == tmp_path / "src" / "ports.py"


def test_src_dir_resolves_a_nested_packaged_directory(tmp_path: Path) -> None:
    _write(tmp_path, "src/memoiq/__init__.py")
    _write(tmp_path, "src/memoiq/mockworld/fakes/fake_clock.py", "x = 1\n")

    assert (
        layout.src_dir(tmp_path, "mockworld", "fakes")
        == tmp_path / "src" / "memoiq" / "mockworld" / "fakes"
    )


def test_src_dir_prefers_the_flat_directory_when_both_exist(tmp_path: Path) -> None:
    flat = tmp_path / "src" / "domain"
    _write(tmp_path, "src/domain/order.py", "x = 1\n")
    _write(tmp_path, "src/memoiq/__init__.py")
    _write(tmp_path, "src/memoiq/domain/order.py", "x = 1\n")

    assert layout.src_dir(tmp_path, "domain") == flat


def test_a_file_does_not_satisfy_a_directory_probe(tmp_path: Path) -> None:
    """``src/domain.py`` is a module, not the ``domain/`` package a probe wants."""
    _write(tmp_path, "pyproject.toml", '[project]\nname = "memoiq"\n')
    _write(tmp_path, "src/domain.py", "x = 1\n")
    _write(tmp_path, "src/memoiq/__init__.py")
    _write(tmp_path, "src/memoiq/domain/order.py", "x = 1\n")

    assert layout.src_dir(tmp_path, "domain") == tmp_path / "src" / "memoiq" / "domain"


def test_a_directory_does_not_satisfy_a_module_probe(tmp_path: Path) -> None:
    """``src/ports/`` (a decomposed package) is not ``src/ports.py``."""
    _write(tmp_path, "pyproject.toml", '[project]\nname = "memoiq"\n')
    _write(tmp_path, "src/ports/__init__.py")
    _write(tmp_path, "src/memoiq/__init__.py")
    _write(tmp_path, "src/memoiq/ports.py", "x = 1\n")

    assert (
        layout.src_module(tmp_path, "ports") == tmp_path / "src" / "memoiq" / "ports.py"
    )


# --- CheckContext delegation ---------------------------------------------


def test_context_resolves_through_the_shared_layout_module(tmp_path: Path) -> None:
    _write(tmp_path, "src/memoiq/__init__.py")
    expected = _write(tmp_path, "src/memoiq/ports.py", "x = 1\n")
    _write(tmp_path, "pyproject.toml", '[project]\nname = "memoiq"\n')

    ctx = CheckContext(root=tmp_path)

    assert ctx.src_packages == ("memoiq",)
    assert ctx.src_module("ports") == expected
    assert ctx.rel(expected) == "src/memoiq/ports.py"


def test_context_rel_falls_back_to_an_absolute_path_off_root(tmp_path: Path) -> None:
    ctx = CheckContext(root=tmp_path / "repo")
    outside = tmp_path / "elsewhere" / "ports.py"

    assert ctx.rel(outside) == outside.as_posix()
