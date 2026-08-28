"""``S605``/``S606`` must stay selected, and must actually fire (#11724).

Four gates declined to flag ``os.system`` on the decision path, each for its
own reason — bandit rates ``B605`` as *Low* while the Makefile gates at
*medium*, ruff did not select ``S`` at all, and the two AST scans named only
HydraFlow's sanctioned helpers. PR #11737 closed the hole for the ten modules
that *claim* not to spawn; these two ruff rules close it repo-wide.

Measured before selecting them: ``S605`` and ``S606`` were both at **zero**
findings, so they cost nothing. ``S607`` (start-process-with-partial-path) was
at 722 — every ``git``/``gh``/``make`` called by name — and is a different
rule about a different thing. It is deliberately NOT selected.

Asserting the codes appear in ``pyproject.toml`` would be a literal check that
passes while ruff ignores them. So the load-bearing test below RUNS ruff
against a planted spawn and asserts each rule fires.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PYPROJECT = _REPO_ROOT / "pyproject.toml"

#: The two rules and a source line each must flag.
_RULES = (("S605", 'os.system("echo hi")'), ("S606", 'os.execv("/bin/ls", ["ls"])'))


def _selected() -> list[str]:
    with _PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)["tool"]["ruff"]["lint"]["select"]


def _ruff(target: Path) -> str:
    """Ruff's output for *target* under the repo's own config."""
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--config",
            str(_PYPROJECT),
            str(target),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=_REPO_ROOT,
    )
    return proc.stdout + proc.stderr


@pytest.mark.parametrize(("rule", "spawn"), _RULES, ids=[r for r, _ in _RULES])
def test_the_rule_actually_fires_on_a_planted_spawn(
    rule: str, spawn: str, tmp_path: Path
) -> None:
    """The load-bearing one: ruff must REPORT, not merely list the code.

    Deleting the rule from ``select`` reddens this. Asserting on the config
    text would not — that is the shape that lets a gate go quiet.
    """
    victim = tmp_path / "planted_spawn.py"
    victim.write_text(f"import os\n\n{spawn}\n", encoding="utf-8")

    out = _ruff(victim)

    assert rule in out, (
        f"{rule} did not fire on {spawn!r}. The rule is not reaching this "
        f"file — selection, per-file-ignores, or exclude is swallowing it.\n{out}"
    )


def test_a_clean_file_is_not_flagged(tmp_path: Path) -> None:
    """Guard the guard: a matcher that flagged everything would prove nothing."""
    clean = tmp_path / "clean.py"
    clean.write_text("import os\n\nprint(os.getcwd())\n", encoding="utf-8")

    out = _ruff(clean)

    for rule, _ in _RULES:
        assert rule not in out, f"{rule} fired on a file that spawns nothing:\n{out}"


def test_s607_stays_unselected() -> None:
    """S607 is a different rule about a different thing, at 722 findings here.

    Pinned so a future 'let's just add the whole S set' does not land it by
    accident and get switched off wholesale a week later.
    """
    assert "S607" not in _selected(), (
        "S607 (start-process-with-partial-path) was selected. It flags every "
        "`git`/`gh`/`make` called by name — 722 sites — and is unrelated to the "
        "shell-spawn hole S605/S606 close. If this is deliberate, it needs its "
        "own decision and a baseline, not a quiet addition here."
    )
