"""#12071: the pin writer promised XPASS surfacing that its marker could not give.

`scripts/triage_regressions.py` documented that "a future fix that flips the
test green will surface as an unexpected pass (XPASS) and we can drop the
marker explicitly rather than silently" — while writing `strict=False`.

pytest reports an unexpected pass under `strict=False` as `x` and exits 0. So a
pin whose bug had been fixed sat RED-labelled forever with nothing pointing at
it. `src/regression_rot_scan.py` exists partly to work around exactly that,
inferring RED-ness statically because "xfail(strict=False) masks the exit code
anyway" — a workaround is evidence the masking was an obstacle, not a choice.

`add_xfail_markers` is exercised directly against a real file on disk. Driving
the whole script was tried first and does not work: it runs the live regression
suite to find failures, so in a temp tree it finds none and writes nothing —
which made the strictness assertion vacuous rather than failing.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT = Path(__file__).parents[2] / "scripts" / "triage_regressions.py"


def _writer():
    """Import the script as a module without executing `main`."""
    spec = importlib.util.spec_from_file_location("triage_regressions", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["triage_regressions"] = module
    spec.loader.exec_module(module)
    return module


def _pin_one(tmp_path: Path, monkeypatch) -> str:
    """Mark one failing test and return the rewritten file."""
    target = tmp_path / "regression_issue_99999.py"
    target.write_text(
        "def test_placeholder() -> None:\n    assert False\n", encoding="utf-8"
    )
    module = _writer()
    monkeypatch.chdir(tmp_path)
    module.add_xfail_markers({f"{target.name}::test_placeholder"})
    return target.read_text(encoding="utf-8")


def test_the_writer_adds_a_marker_at_all(tmp_path: Path, monkeypatch) -> None:
    """Anti-vacuity floor: the strictness assertion is empty with no marker."""
    assert "pytest.mark.xfail" in _pin_one(tmp_path, monkeypatch)


def test_a_new_pin_is_strict(tmp_path: Path, monkeypatch) -> None:
    """The behaviour the docstring promised: a landed fix must fail the run."""
    written = _pin_one(tmp_path, monkeypatch)

    assert "strict=True" in written, (
        "the pin writer emitted a non-strict marker; an unexpected pass would "
        "be reported as `x` with exit 0, so a fixed bug's pin stays RED "
        "forever with nothing pointing at it"
    )
    assert "strict=False" not in written


def test_the_docstring_names_the_strictness_it_actually_emits() -> None:
    """The mismatch is the defect: the claim and the marker must agree.

    Checked on the strictness token rather than on the word "XPASS" — an
    earlier version of this test looked for the acronym and failed the moment
    the docstring described the same behaviour in plain words, which is the
    test policing prose instead of the property.
    """
    source = _SCRIPT.read_text(encoding="utf-8")
    split = source.index("from __future__")
    docstring, body = source[:split], source[split:]

    emitted = "strict=True" if 'f"strict=True)' in body else "strict=False"

    assert emitted in docstring, (
        f"the writer emits {emitted} markers but its docstring never says so; "
        f"#12071 was a docstring promising behaviour the marker could not give"
    )
