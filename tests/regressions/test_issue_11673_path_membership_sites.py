"""#11673 — the remaining path-membership collections resolve, and follow packages.

Every collection here is a set of module paths used as a membership test. The
class failure is that an entry stops matching the day its module becomes a
package, and **nothing reddens**: a membership test that matches nothing is
indistinguishable from one that does not match *this* input.

Before #11672 only two collections in the repo asserted their entries resolved
on disk. That single assertion is what exposed ``src/coordinator.py`` and
``src/persistence/``, neither of which has ever existed in this repo.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src"

sys.path.insert(0, str(_SRC))


def _resolves(module_stem: str) -> bool:
    """A stem is a module identity: either a file or a package satisfies it."""
    return (_SRC / f"{module_stem}.py").is_file() or (_SRC / module_stem).is_dir()


# --- fake_coverage_auditor_loop._FAKE_REAL_SURFACE_SOURCES -------------------


def _fake_surface_stems() -> list[tuple[str, str, str]]:
    from fake_coverage_auditor_loop import _FAKE_REAL_SURFACE_SOURCES

    return [
        (fake, stem, cls)
        for fake, sources in _FAKE_REAL_SURFACE_SOURCES.items()
        for stem, cls in sources
    ]


def test_fake_real_surface_sources_all_resolve() -> None:
    """The permissive-degradation site — the highest-risk of the class.

    A stem that resolves to nothing contributes no methods, but ``resolved_any``
    stays True on the strength of its siblings, so the real surface silently
    SHRINKS and the auditor reclassifies genuine un-cassetted methods as
    fake-only scaffolding. It stops reporting real gaps and stays green.
    """
    dead = [
        f"{fake}: {stem}.{cls}"
        for fake, stem, cls in _fake_surface_stems()
        if not _resolves(stem)
    ]
    assert not dead, (
        f"_FAKE_REAL_SURFACE_SOURCES names modules that no longer resolve: "
        f"{dead}. Each one silently shrinks the real surface."
    )


def test_fake_real_surface_follows_a_module_into_a_package(tmp_path: Path) -> None:
    """Resolution must accept a package, not just a file.

    Built SYNTHETICALLY rather than by iterating the live stems. The first
    version of this test looped over stems that are packages *today* — there
    are none, so the loop body never ran and the test passed with the package
    branch deleted. A guard for a decomposition that has not happened yet
    cannot be written against the current tree; it has to construct one.
    """
    from fake_coverage_auditor_loop import _module_source_files

    src = tmp_path / "src"
    (src / "decomposed").mkdir(parents=True)
    (src / "decomposed" / "__init__.py").write_text("")
    (src / "decomposed" / "_part.py").write_text("class Thing:\n    pass\n")
    (src / "nested" / "deep").mkdir(parents=True)
    (src / "nested" / "deep" / "_leaf.py").write_text("class Deep:\n    pass\n")
    (src / "single.py").write_text("class Single:\n    pass\n")

    found = _module_source_files(src, "decomposed")
    assert {f.name for f in found} == {"__init__.py", "_part.py"}, (
        "a decomposed module resolved to no source files — every method it "
        "defines silently drops out of the real surface"
    )
    assert {f.name for f in _module_source_files(src, "nested")} == {"_leaf.py"}, (
        "resolution is not recursive: a nested package member drops out"
    )
    assert [f.name for f in _module_source_files(src, "single")] == ["single.py"]
    assert _module_source_files(src, "definitely_not_a_module_11673") == ()


def test_fake_real_surface_is_not_empty() -> None:
    assert _fake_surface_stems(), "collection is empty — every guard here is vacuous"


# --- prompt_fitness.EXCLUDED_MODULES ----------------------------------------


def test_excluded_modules_are_keyed_on_a_real_dotted_identity() -> None:
    """A key that matches nothing silently stops excluding its module."""
    from prompt_fitness import EXCLUDED_MODULES

    assert EXCLUDED_MODULES, "empty exclusion map — nothing to protect"
    dead = [k for k in EXCLUDED_MODULES if not _resolves(k.replace(".", "/"))]
    assert not dead, (
        f"EXCLUDED_MODULES keys that resolve to no module: {dead}. A stale key "
        "excludes nothing, so the module silently re-enters the prompt sweep."
    )


def test_excluded_modules_no_longer_match_on_bare_stem() -> None:
    """Stem keying excludes a same-named module in ANY package."""
    from prompt_fitness import EXCLUDED_MODULES

    assert "_skill_prompt_eval" not in EXCLUDED_MODULES
    assert "state._skill_prompt_eval" in EXCLUDED_MODULES


def test_the_excluded_module_is_still_actually_excluded(  # noqa: D103
) -> None:
    from prompt_fitness import discovered_builders

    assert not [m for m in discovered_builders() if m.endswith("_skill_prompt_eval")]


# --- non-recursive globs that would lapse on the next decomposition ---------


@pytest.mark.parametrize(
    ("module", "attr"),
    [
        ("impacted_tests", "ARCHITECTURE_GLOBS"),
    ],
)
def test_architecture_floor_glob_is_recursive(module: str, attr: str) -> None:
    """The always-on CI floor must not shrink when a subdirectory appears."""
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))
    mod = __import__(module)
    globs = getattr(mod, attr)
    assert any("**" in g for g in globs), (
        f"{module}.{attr} is non-recursive: a future "
        "tests/architecture/<sub>/test_*.py drops out of the floor silently."
    )


def test_sandbox_seam_scan_enumerates_a_runner_as_a_unit() -> None:
    """The loop half was fixed; the runner half was its unfixed twin."""
    scan = (_REPO_ROOT / "tests/architecture/sandbox_seam_scan.py").read_text()
    assert '_runner") if d.is_dir()' in scan or '*_runner")' in scan, (
        "sandbox_seam_scan no longer folds decomposed runner packages in"
    )
