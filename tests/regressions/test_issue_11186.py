"""Regression test for issue #11186 — ADR-drift regression pins must self-retire.

Bug: ``tests/regressions/test_issue_9419_9421_adr_drift.py`` resolves its six
pinned ADRs (0012/0024/0044/0045/0050/0064) two different ways, both of them
*total* lookups that raise on routine ADR maintenance instead of retiring
gracefully:

  * ``_single_adr_index`` did ``next(a for a in index.adrs() if a.number ==
    number)`` — raises ``StopIteration`` the moment a pinned ADR is removed
    or renumbered.
  * ``test_parse_picks_up_qualified_symbols_for_each_right_sized_adr`` did
    ``parse_adr_file(_ADR_DIR / _RIGHT_SIZED[number])`` against a hard-coded
    filename map — raises ``FileNotFoundError`` for the same reason.

Neither path skips when a pinned ADR moves off ``Accepted``/``Proposed``
(Superseded, Deprecated) either — production's own drift logic
(``ADRIndex.adrs_touching``) silently excludes non-live ADRs, so a
superseded pin still tries to assert real drift and gets a plain assertion
failure instead of a graceful retirement.

This is the exact convention violation #11180 flagged in
``test_issue_10440.py`` — see the ``adr-drift-regression-test-conventions``
wiki entry: ADR-drift regression pins must resolve ADRs by number through
``ADRIndex`` and self-retire (skip/return early) when the target is absent,
renumbered, or not live, so routine ADR maintenance doesn't redden an
unrelated PR.

This meta-guard proves both the defect and the fix without stubbing
anything: it copies the real pin module into a throwaway repo tree whose
``docs/adr`` corpus has one pinned ADR mutated (removed, renumbered, or
flipped to Superseded), symlinks the real ``src/`` tree so every other pin
still resolves real files, and runs the copied module under a real `pytest`
subprocess. A defective pin module either errors (StopIteration /
FileNotFoundError surfacing as an uncaught exception) or fails an assertion
(the superseded case); a self-retiring one only ever skips the mutated
ADR's cases while every other case still runs for real.

A companion anti-vacuity check (against the real, unmutated corpus) proves
the liveness gate isn't so wide it quietly retires cases that should still
run — 0 skips are expected there.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ADR_DIR = _REPO_ROOT / "docs" / "adr"
_PIN_MODULE = _REPO_ROOT / "tests" / "regressions" / "test_issue_9419_9421_adr_drift.py"

# Two of the six right-sized ADRs: 45 is a plain Accepted pin, 64 additionally
# carries the deliberately-bare-data-module assertion
# (test_adr_0064_data_modules_still_drift_by_design), so mutating it also
# exercises that pin's own liveness gating.
_TARGET_NUMBERS = (45, 64)
_FATES = ("remove", "renumber", "superseded")

# Own private copy of a Status-line matcher (mirrors adr_index's), per the
# repo convention that modules — including test fixtures — own their regex
# copies rather than importing another module's `_`-prefixed internals.
_STATUS_LINE_RE = re.compile(r"(\*\*Status:\*\*\s*)(\S.*)$", re.MULTILINE)


def _adr_filename(number: int) -> str:
    matches = list(_ADR_DIR.glob(f"{number:04d}-*.md"))
    assert len(matches) == 1, (
        f"expected exactly one ADR-{number:04d} file, got {matches}"
    )
    return matches[0].name


def _mutate(target: Path, number: int, fate: str) -> None:
    if fate == "remove":
        target.unlink()
        return

    if fate == "renumber":
        new_number = number + 9000
        old_marker, new_marker = f"ADR-{number:04d}", f"ADR-{new_number:04d}"
        text = target.read_text()
        assert old_marker in text, (
            f"could not find {old_marker!r} to renumber in {target}"
        )
        target.write_text(text.replace(old_marker, new_marker))
        target.rename(
            target.with_name(target.name.replace(f"{number:04d}", f"{new_number:04d}"))
        )
        return

    if fate == "superseded":
        text = target.read_text()
        new_text, count = _STATUS_LINE_RE.subn(
            r"\1Superseded by ADR-0001", text, count=1
        )
        assert count == 1, f"could not find a Status line to mutate in {target}"
        target.write_text(new_text)
        return

    raise ValueError(f"unknown fate: {fate}")


def _build_fake_repo(
    tmp_path: Path, *, mutation: tuple[int, str] | None = None
) -> Path:
    """Build a throwaway repo tree mirroring enough of the real one for the
    pin module to run: a copy of docs/adr (optionally mutated) plus a
    symlink to the real src/ so every unmutated ADR still resolves real
    source files."""
    fake_root = tmp_path / "fake_repo"
    shutil.copytree(_ADR_DIR, fake_root / "docs" / "adr")

    if mutation is not None:
        number, fate = mutation
        target = fake_root / "docs" / "adr" / _adr_filename(number)
        _mutate(target, number, fate)

    pin_dir = fake_root / "tests" / "regressions"
    pin_dir.mkdir(parents=True)
    shutil.copy(_PIN_MODULE, pin_dir / _PIN_MODULE.name)
    (fake_root / "src").symlink_to(_REPO_ROOT / "src")
    return fake_root


def _run_module_tests(fake_root: Path) -> dict[str, str]:
    """Run the copied pin module under *fake_root* via a real pytest
    subprocess and return {test name: outcome} from its JUnit report.

    Outcome is one of 'passed' | 'skipped' | 'failed' | 'error'.
    """
    module_path = fake_root / "tests" / "regressions" / _PIN_MODULE.name
    junit_path = fake_root / "junit.xml"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(fake_root / "src")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(module_path),
            "-q",
            "--no-header",
            f"--junit-xml={junit_path}",
        ],
        cwd=fake_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,  # non-zero == real test failures inside the subprocess, not an error here
    )
    assert junit_path.is_file(), (
        "pytest never produced a report — the pin module likely failed to "
        f"import:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    outcomes: dict[str, str] = {}
    for case in ElementTree.parse(junit_path).getroot().iter("testcase"):
        name = case.get("name", "")
        if case.find("skipped") is not None:
            outcomes[name] = "skipped"
        elif case.find("failure") is not None:
            outcomes[name] = "failed"
        elif case.find("error") is not None:
            outcomes[name] = "error"
        else:
            outcomes[name] = "passed"
    return outcomes


@pytest.mark.parametrize("fate", _FATES)
@pytest.mark.parametrize("number", _TARGET_NUMBERS)
def test_mutated_pinned_adr_self_retires_without_blowup(
    tmp_path: Path, number: int, fate: str
) -> None:
    """Removing, renumbering, or superseding a pinned ADR must not error or
    fail the pin module — only skip the cases that name it (#11186)."""
    fake_root = _build_fake_repo(tmp_path, mutation=(number, fate))
    outcomes = _run_module_tests(fake_root)

    assert outcomes, "pin module produced no test outcomes at all"
    assert "error" not in outcomes.values(), (
        f"pin module blew up (uncaught exception) for ADR-{number:04d} "
        f"under fate={fate}: {outcomes}"
    )
    assert "failed" not in outcomes.values(), (
        f"pin module failed an assertion for ADR-{number:04d} under "
        f"fate={fate} instead of self-retiring: {outcomes}"
    )
    assert "skipped" in outcomes.values(), (
        f"expected ADR-{number:04d} under fate={fate} to self-retire (skip) "
        f"at least one case, but nothing skipped: {outcomes}"
    )


def test_real_repo_pins_do_not_retire(tmp_path: Path) -> None:
    """Anti-vacuity: against the real, unmutated docs/adr, every pin case
    actually executes — the liveness gate must not be so wide that it
    quietly retires cases that should still run for real (#11186)."""
    fake_root = _build_fake_repo(tmp_path)
    outcomes = _run_module_tests(fake_root)

    assert outcomes, "pin module produced no test outcomes at all"
    assert "error" not in outcomes.values(), f"unexpected error(s): {outcomes}"
    assert "failed" not in outcomes.values(), f"unexpected failure(s): {outcomes}"
    skipped = {
        name: outcome for name, outcome in outcomes.items() if outcome == "skipped"
    }
    assert not skipped, (
        f"pin case(s) retired against the real, unmutated docs/adr — the "
        f"liveness gate is too wide: {skipped}"
    )
