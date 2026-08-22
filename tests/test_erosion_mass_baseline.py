"""Unit tests for the mass baseline (grandfather set + ratchet diff)."""

from __future__ import annotations

from pathlib import Path

import pytest

from erosion.mass_baseline import (
    MassBaseline,
    grown,
    load_mass_baseline,
    new_god_classes,
    new_god_files,
    refresh_entries,
    save_mass_baseline,
    write_mass_baseline,
)
from erosion.models import GodClass, GodFile, MassFinding


def _finding(
    files: tuple[GodFile, ...] = (), classes: tuple[GodClass, ...] = ()
) -> MassFinding:
    return MassFinding(
        god_files=files,
        god_classes=classes,
        total_files=10,
        file_loc_threshold=1500,
        class_loc_threshold=600,
        class_method_threshold=40,
    )


def test_missing_baseline_loads_empty(tmp_path: Path) -> None:
    baseline = load_mass_baseline(tmp_path / "nope.yaml")
    assert baseline == MassBaseline()
    assert baseline.files == {} and baseline.classes == {}


def test_save_then_load_round_trips(tmp_path: Path) -> None:
    finding = _finding(
        files=(GodFile("src/config.py", 7134),),
        classes=(GodClass("src/config.py", "HydraFlowConfig", 4894, 39),),
    )
    path = tmp_path / "mass.yaml"
    save_mass_baseline(path, finding, comment="initial")

    loaded = load_mass_baseline(path)

    assert loaded.comment == "initial"
    assert loaded.files == {"src/config.py": 7134}
    assert loaded.classes == {
        "src/config.py:HydraFlowConfig": {"loc": 4894, "methods": 39}
    }


def test_new_god_files_and_classes_are_those_absent_from_baseline() -> None:
    baseline = MassBaseline(
        files={"old.py": 2000}, classes={"old.py:Old": {"loc": 900, "methods": 10}}
    )
    finding = _finding(
        files=(GodFile("old.py", 2100), GodFile("new.py", 1600)),
        classes=(GodClass("old.py", "Old", 950, 12), GodClass("new.py", "New", 700, 5)),
    )
    assert new_god_files(finding, baseline) == (GodFile("new.py", 1600),)
    assert new_god_classes(finding, baseline) == (GodClass("new.py", "New", 700, 5),)


def test_grown_reports_entries_past_tolerance_only() -> None:
    baseline = MassBaseline(
        files={"f.py": 1000, "g.py": 1000},
        classes={"f.py:F": {"loc": 500, "methods": 10}},
    )
    finding = _finding(
        files=(GodFile("f.py", 1150), GodFile("g.py", 1050)),
        classes=(GodClass("f.py", "F", 600, 10),),
    )
    growth = grown(finding, baseline, tolerance=0.10)
    assert [(g.key, g.kind, g.baseline_loc, g.loc) for g in growth] == [
        ("f.py", "file", 1000, 1150),
        ("f.py:F", "class", 500, 600),
    ]


def test_shrunk_entries_never_count_as_grown() -> None:
    baseline = MassBaseline(files={"f.py": 2000})
    finding = _finding(files=(GodFile("f.py", 1700),))
    assert grown(finding, baseline) == ()


# --- both god-making axes are watched ------------------------------------
# A class is a god class when EITHER its LOC or its method count crosses the
# threshold (erosion.mass), so growth has to be reported on either axis too.
# `AgentRunner` is the live proof: it SHRANK 1408 → 1388 LOC while gaining six
# methods (36 → 42), and a LOC-only reading called that "not grown".


@pytest.mark.parametrize(
    ("loc", "methods", "expect_reported", "expect_loc_grew", "expect_methods_grew"),
    [
        pytest.param(670, 10, True, True, False, id="loc-only"),
        pytest.param(590, 12, True, False, True, id="methods-only"),
        pytest.param(670, 12, True, True, True, id="both-axes"),
        pytest.param(660, 10, False, False, False, id="loc-exactly-at-tolerance"),
        pytest.param(600, 11, False, False, False, id="methods-exactly-at-tolerance"),
        pytest.param(400, 4, False, False, False, id="shrank-on-both-axes"),
    ],
)
def test_grown_watches_loc_and_method_axes(
    loc: int,
    methods: int,
    expect_reported: bool,
    expect_loc_grew: bool,
    expect_methods_grew: bool,
) -> None:
    baseline = MassBaseline(classes={"f.py:F": {"loc": 600, "methods": 10}})
    finding = _finding(classes=(GodClass("f.py", "F", loc, methods),))

    growth = grown(finding, baseline, tolerance=0.10)

    assert bool(growth) is expect_reported
    if expect_reported:
        assert (growth[0].grew_loc, growth[0].grew_methods) == (
            expect_loc_grew,
            expect_methods_grew,
        )
        assert (growth[0].baseline_methods, growth[0].methods) == (10, methods)


def test_grown_file_entries_carry_no_method_axis() -> None:
    baseline = MassBaseline(files={"f.py": 1000})
    finding = _finding(files=(GodFile("f.py", 1200),))

    (growth,) = grown(finding, baseline, tolerance=0.10)

    assert growth.grew_methods is False
    assert (growth.baseline_methods, growth.methods) == (0, 0)


# --- targeted refresh (`--only`) -----------------------------------------


def _mixed_baseline() -> MassBaseline:
    return MassBaseline(
        files={"a.py": 1600, "b.py": 1700},
        classes={
            "a.py:A": {"loc": 700, "methods": 20},
            "b.py:B": {"loc": 800, "methods": 30},
        },
        comment="original",
    )


@pytest.mark.parametrize(
    ("key", "expect_updated", "expect_removed"),
    [
        pytest.param("a.py:A", ("a.py:A",), (), id="class-still-a-god-is-updated"),
        pytest.param("b.py:B", (), ("b.py:B",), id="class-below-threshold-is-removed"),
        pytest.param("a.py", ("a.py",), (), id="file-still-a-god-is-updated"),
        pytest.param("b.py", (), ("b.py",), id="file-below-threshold-is-removed"),
    ],
)
def test_refresh_entries_updates_or_removes_the_named_entry(
    key: str, expect_updated: tuple[str, ...], expect_removed: tuple[str, ...]
) -> None:
    # `a.py`/`a.py:A` are still over threshold and grew; `b.py`/`b.py:B` are gone
    # from the live reading entirely (decomposed below threshold).
    finding = _finding(
        files=(GodFile("a.py", 1900),),
        classes=(GodClass("a.py", "A", 950, 26),),
    )

    refreshed, updated, removed = refresh_entries(_mixed_baseline(), finding, [key])

    assert (updated, removed) == (expect_updated, expect_removed)
    if expect_removed:
        assert key not in refreshed.files and key not in refreshed.classes
    else:
        assert key in refreshed.files or key in refreshed.classes


def test_refresh_entries_records_the_live_numbers_for_the_named_entry() -> None:
    finding = _finding(
        files=(GodFile("a.py", 1900),),
        classes=(GodClass("a.py", "A", 950, 26),),
    )

    refreshed, _, _ = refresh_entries(_mixed_baseline(), finding, ["a.py:A", "a.py"])

    assert refreshed.classes["a.py:A"] == {"loc": 950, "methods": 26}
    assert refreshed.files["a.py"] == 1900


def test_refresh_entries_leaves_every_other_entry_untouched() -> None:
    """The whole point of `--only`: no unrelated growth is laundered through the PR."""
    finding = _finding(
        files=(GodFile("a.py", 1900), GodFile("b.py", 2400)),
        classes=(GodClass("a.py", "A", 950, 26), GodClass("b.py", "B", 1200, 44)),
    )

    refreshed, _, _ = refresh_entries(_mixed_baseline(), finding, ["a.py:A"])

    assert refreshed.files == {"a.py": 1600, "b.py": 1700}
    assert refreshed.classes["b.py:B"] == {"loc": 800, "methods": 30}
    assert refreshed.comment == "original"


def test_refresh_entries_reports_no_update_when_the_entry_is_already_accurate() -> None:
    finding = _finding(classes=(GodClass("a.py", "A", 700, 20),))

    refreshed, updated, removed = refresh_entries(
        _mixed_baseline(), finding, ["a.py:A"]
    )

    assert (updated, removed) == ((), ())
    assert refreshed.classes["a.py:A"] == {"loc": 700, "methods": 20}


@pytest.mark.parametrize(
    "key",
    [
        pytest.param("typo.py:Nope", id="unknown-class"),
        pytest.param("typo.py", id="unknown-file"),
    ],
)
def test_refresh_entries_rejects_a_key_that_is_neither_baselined_nor_live(
    key: str,
) -> None:
    with pytest.raises(KeyError, match="not in the baseline"):
        refresh_entries(_mixed_baseline(), _finding(), [key])


def test_targeted_refresh_rewrites_only_the_named_lines_on_disk(
    tmp_path: Path,
) -> None:
    """Byte-level guard: untouched entries serialize identically after a refresh."""
    path = tmp_path / "mass.yaml"
    write_mass_baseline(path, _mixed_baseline())
    before = path.read_text(encoding="utf-8").splitlines()

    finding = _finding(
        files=(GodFile("a.py", 1900), GodFile("b.py", 1700)),
        classes=(
            GodClass("a.py", "A", 950, 26),
            GodClass("b.py", "B", 800, 30),
        ),
    )
    refreshed, _, _ = refresh_entries(_mixed_baseline(), finding, ["a.py:A"])
    write_mass_baseline(path, refreshed)
    after = path.read_text(encoding="utf-8").splitlines()

    changed = [line for line in after if line not in before]
    assert changed == ["    loc: 950", "    methods: 26"]
