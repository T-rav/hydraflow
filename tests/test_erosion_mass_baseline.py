"""Unit tests for the mass baseline (grandfather set + ratchet diff)."""

from __future__ import annotations

from pathlib import Path

from erosion.mass_baseline import (
    MassBaseline,
    grown,
    load_mass_baseline,
    new_god_classes,
    new_god_files,
    save_mass_baseline,
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
