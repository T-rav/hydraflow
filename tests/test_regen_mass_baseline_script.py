"""Tests for scripts/regen_mass_baseline.py — blanket vs targeted baseline moves.

The engine (``erosion.mass_baseline``) is covered by
``test_erosion_mass_baseline.py``; these tests cover the script's own contract:
``--reason`` is always required, the default is the blanket re-snapshot that
already existed, and ``--only`` rewrites exactly the named entries so a
decomposition PR can record the two entries it shrank without laundering every
other class's unrelated growth through its diff (#11646).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "regen_mass_baseline.py"

_BIG_CLASS = "class Hub:\n" + "".join(
    f"    def m{i}(self):\n        return {i}\n" for i in range(45)
)
_SMALL_CLASS = "class Calm:\n    def only(self):\n        return 1\n"


def _load_cli() -> ModuleType:
    spec = importlib.util.spec_from_file_location("regen_mass_baseline", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def src_tree(tmp_path: Path) -> Path:
    """A source tree with one god class (`Hub`) and one ordinary class."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "hub.py").write_text(_BIG_CLASS, encoding="utf-8")
    (src / "calm.py").write_text(_SMALL_CLASS, encoding="utf-8")
    return src


def _write_baseline(path: Path, payload: dict[str, object]) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")


def _run(module: ModuleType, *args: str) -> int:
    return int(module.main(list(args)))


def test_blanket_regen_snapshots_every_entry(src_tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "mass.yaml"

    assert (
        _run(_load_cli(), "--reason", "why", "--src", str(src_tree), "--out", str(out))
        == 0
    )

    payload = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert payload["classes"] == {"src/hub.py:Hub": {"loc": 91, "methods": 45}}
    assert "why" in payload["comment"]


def test_targeted_regen_rewrites_only_the_named_entry(
    src_tree: Path, tmp_path: Path
) -> None:
    out = tmp_path / "mass.yaml"
    _write_baseline(
        out,
        {
            "comment": "original",
            "files": {"src/elsewhere.py": 1600},
            "classes": {
                "src/hub.py:Hub": {"loc": 10, "methods": 41},
                "src/other.py:Other": {"loc": 700, "methods": 20},
            },
        },
    )

    code = _run(
        _load_cli(),
        "--reason",
        "recorded Hub's reviewed size",
        "--only",
        "src/hub.py:Hub",
        "--src",
        str(src_tree),
        "--out",
        str(out),
    )

    assert code == 0
    payload = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert payload["classes"]["src/hub.py:Hub"] == {"loc": 91, "methods": 45}
    # Untouched entries keep their recorded numbers — no laundering.
    assert payload["classes"]["src/other.py:Other"] == {"loc": 700, "methods": 20}
    assert payload["files"] == {"src/elsewhere.py": 1600}


def test_targeted_regen_drops_an_entry_that_fell_below_threshold(
    src_tree: Path, tmp_path: Path
) -> None:
    out = tmp_path / "mass.yaml"
    _write_baseline(
        out,
        {
            "comment": "original",
            "files": {},
            "classes": {
                "src/calm.py:Calm": {"loc": 900, "methods": 30},
                "src/hub.py:Hub": {"loc": 91, "methods": 45},
            },
        },
    )

    code = _run(
        _load_cli(),
        "--reason",
        "decomposed Calm",
        "--only",
        "src/calm.py:Calm",
        "--src",
        str(src_tree),
        "--out",
        str(out),
    )

    assert code == 0
    payload = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert "src/calm.py:Calm" not in payload["classes"]
    assert payload["classes"]["src/hub.py:Hub"] == {"loc": 91, "methods": 45}


def test_targeted_regen_refuses_an_unknown_key(src_tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "mass.yaml"
    _write_baseline(out, {"comment": "original", "files": {}, "classes": {}})
    before = out.read_text(encoding="utf-8")

    code = _run(
        _load_cli(),
        "--reason",
        "typo",
        "--only",
        "src/nope.py:Ghost",
        "--src",
        str(src_tree),
        "--out",
        str(out),
    )

    assert code == 1
    assert out.read_text(encoding="utf-8") == before


def test_targeted_regen_writes_nothing_when_the_entry_is_already_accurate(
    src_tree: Path, tmp_path: Path
) -> None:
    """No move, no diff — a 'Last moved' stamp on an unchanged baseline is the rot."""
    out = tmp_path / "mass.yaml"
    _write_baseline(
        out,
        {
            "comment": "original",
            "files": {},
            "classes": {"src/hub.py:Hub": {"loc": 91, "methods": 45}},
        },
    )
    before = out.read_text(encoding="utf-8")

    code = _run(
        _load_cli(),
        "--reason",
        "nothing to do",
        "--only",
        "src/hub.py:Hub",
        "--src",
        str(src_tree),
        "--out",
        str(out),
    )

    assert code == 0
    assert out.read_text(encoding="utf-8") == before


def test_reason_is_required() -> None:
    with pytest.raises(SystemExit):
        _run(_load_cli(), "--only", "src/hub.py:Hub")
