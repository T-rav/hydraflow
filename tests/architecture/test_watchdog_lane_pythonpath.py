"""Every Makefile lane that loads the spin watchdog must carry PROJECT_ROOT.

The Makefile states the rule in prose, above ``HF_PYTEST_WATCHDOG``:

    Lanes loading this MUST also carry $(PROJECT_ROOT) on PYTHONPATH: the
    Makefile drives pytest through `uv run pytest`, a console script, which
    does NOT put cwd on sys.path — so `-p tests.hf_spin_watch` fails with
    `No module named 'tests'` ...

Stated in prose, pinned nowhere. Four lanes obeyed it and ``make test`` did not,
so the target a developer is most likely to reach for died on startup with
exactly the error the comment predicts — while the same command under
``python -m pytest`` (which DOES put cwd on sys.path) worked, making it look
like an environment problem rather than a Makefile one.

Derived from the Makefile rather than listing the lanes: a hand-copied list
would be the same N-1 one recipe later.
"""

from __future__ import annotations

import re
from pathlib import Path

_MAKEFILE = Path(__file__).resolve().parents[2] / "Makefile"
#: Variables whose expansion contains ``-p tests.hf_spin_watch``.
_WATCHDOG_VARS = ("$(PYTEST_PARALLEL)", "$(HF_PYTEST_WATCHDOG)")
_PYTHONPATH = re.compile(r"PYTHONPATH=(\S+)")


def _watchdog_recipe_lines() -> list[tuple[int, str]]:
    """Recipe lines (tab-indented) that load the watchdog into a pytest run."""
    out: list[tuple[int, str]] = []
    for number, line in enumerate(
        _MAKEFILE.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.startswith("\t"):
            continue  # a definition, not an invocation
        if any(var in line for var in _WATCHDOG_VARS):
            out.append((number, line))
    return out


def test_the_sweep_finds_the_lanes_it_is_meant_to_guard() -> None:
    """Anti-vacuity: an empty sweep would make the assertion below serene."""
    lines = _watchdog_recipe_lines()
    assert len(lines) >= 4, (
        f"only {len(lines)} watchdog-loading recipe lines found in {_MAKEFILE} — "
        "the variable was probably renamed, and this guard is now watching "
        "nothing"
    )


def test_every_watchdog_lane_carries_project_root() -> None:
    """Collected over the whole derived set, not one representative of it.

    Deliberately NOT ``@pytest.mark.parametrize`` over a module-level sequence:
    that shape must be classified in ``guard_enumeration_registry`` with a
    ``detects_drop`` resolving a DIFFERENT object than the members, and the
    Makefile is the only place these lanes exist — there is no second artifact
    to check against, and a subject with no detector is ratcheted shrink-only.
    Iterating the same derived set here keeps the coverage the standard asks
    for (``docs/standards/parametrised_guards``) without registering a
    detector that could only re-read its own source.
    """
    offenders: list[str] = []
    for number, line in _watchdog_recipe_lines():
        match = _PYTHONPATH.search(line)
        if match is None:
            offenders.append(f"Makefile:{number} sets no PYTHONPATH at all")
        elif "PROJECT_ROOT" not in match.group(1):
            offenders.append(
                f"Makefile:{number} has PYTHONPATH={match.group(1)}, "
                "which omits $(PROJECT_ROOT)"
            )

    assert not offenders, (
        "These Makefile lanes load `-p tests.hf_spin_watch` without "
        "$(PROJECT_ROOT) on PYTHONPATH:\n  "
        + "\n  ".join(offenders)
        + "\n`uv run pytest` is a console script and does NOT put cwd on "
        "sys.path, so each of these dies on startup with `No module named "
        "'tests'` — while the same command under `python -m pytest` works, "
        "which is what makes it read as an environment problem instead of a "
        "Makefile one."
    )
