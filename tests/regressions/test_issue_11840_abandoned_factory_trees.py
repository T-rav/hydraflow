"""Regression (#11840): abandoned `make factory` trees must be reported.

Measured 2026-08-30: three complete `make factory` trees from 00:35, 00:37 and
00:38 were still alive at 21:30 — 24 processes, PPID=1, holding ports 5556-5558
and running orphaned vite watchers for 21 hours. `_check_stray_quality_processes`
reported PASS the whole time: its markers are `make quality` / `pytest tests/`,
so a leaked factory matches none of them.

Two traps this file pins, both found by getting them wrong first:

1.  **Age is the wrong axis.** A healthy factory is legitimately hours old, so
    appending `"make factory"` to the age-based markers would flag the WORKING
    factory forever. The discriminator is structural: a factory group with no
    live `python -m server` has lost the thing it exists to supervise.

2.  **Substring matching cannot see the difference.** The group keeps a
    supervisor shell whose own command text contains the launch line
    (``sh -c ... uv run --active python -m server & wait``). Measured on the
    live host, ``grep -c 'python -m server'`` gave **2** for the abandoned tree
    and **4** for the healthy one — both non-zero, so a substring check calls
    every tree healthy and never fires. Anchoring to the executable gave 0 vs 1.

The decoy rows are not hypothetical. On a host running LLM agents, `ps` is full
of processes *talking about* the target: the factory's own triage agent carries
`make factory` inside its prompt, and the monitoring shell carries it in its own
command line. A selection predicate that greps for the phrase matches both — and
the triage agent is live factory work.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from preflight import _abandoned_factory_groups

MAKE = "/Library/Developer/CommandLineTools/usr/bin/make"
VENV = "/Users/travisf/.hydraflow/factory-workspace/hydraflow/.venv/bin"
UI = "/Users/travisf/.hydraflow/factory-workspace/hydraflow/src/ui"

# The supervisor shell. Its TEXT names the server it launches — this row is what
# makes a naive `python -m server` substring count non-zero for a dead tree.
_SUPERVISOR = (
    "/bin/sh -c trap 'kill 0' EXIT; cd " + UI + " && ui-npm.sh run dev & "
    "cd .. && PYTHONPATH=src uv run --active python -m server & wait"
)

_HEALTHY = f"""\
71770 71772 34:20 {MAKE} factory
71770 71773 34:20 {MAKE} run
71770 71800 34:15 {_SUPERVISOR}
71770 71871 34:15 {VENV}/python3 -m server
71770 71880 34:15 node {UI}/node_modules/.bin/vite
"""

_ABANDONED = f"""\
38812 38824 20:58:42 {MAKE} factory
38812 38836 20:58:42 {MAKE} run
38812 38902 20:58:41 {_SUPERVISOR}
38812 38943 20:58:40 node {UI}/node_modules/.bin/vite
"""

# Live factory work whose PROMPT contains the hunted phrase.
_DECOY_AGENT = (
    '13148 13148 00:28 claude -p You are a triage agent. Run `make factory` '
    "and check the server starts with python -m server before triaging\n"
)

# The watcher's own shell, carrying the predicate it is testing.
_DECOY_MONITOR = (
    "13771 13771 00:00 /bin/zsh -c ps -eo pgid,command | grep '/make factory' "
    "| awk '$1!=m'\n"
)

_HEADER = "  PGID   PID     ELAPSED COMMAND\n"


def _ps(*blocks: str) -> str:
    return _HEADER + "".join(blocks)


def test_abandoned_tree_is_reported() -> None:
    assert _abandoned_factory_groups(_ps(_ABANDONED)) == ["38812"]


def test_healthy_tree_is_not_reported() -> None:
    """The live factory has a real server, so it is never stray — at any age.

    This is the assertion that forbids reusing the age-based marker list: the
    healthy fixture is 34 minutes old here, but the real one runs for days.
    """
    assert _abandoned_factory_groups(_ps(_HEALTHY)) == []


def test_healthy_tree_is_not_reported_even_when_older_than_the_stray_cutoff() -> None:
    aged = _HEALTHY.replace("34:20", "26:14:03").replace("34:15", "26:14:03")
    assert _abandoned_factory_groups(_ps(aged)) == []


def test_decoy_rows_that_merely_mention_the_target_are_not_reported() -> None:
    """A two-tree fixture passes against the broken substring predicate.

    These rows are why the fixture needs a third case. The agent row is live
    factory work: a sweep that selected it would be pointing an operator at the
    process doing the job.
    """
    assert _abandoned_factory_groups(_ps(_DECOY_AGENT, _DECOY_MONITOR)) == []


def test_abandoned_is_separated_from_healthy_and_decoys_together() -> None:
    """The whole point: exactly one pgid out of a realistic host."""
    out = _ps(_HEALTHY, _ABANDONED, _DECOY_AGENT, _DECOY_MONITOR)
    assert _abandoned_factory_groups(out) == ["38812"]


def test_supervisor_text_alone_does_not_count_as_a_running_server() -> None:
    """Pins the measured 2-vs-4 failure directly.

    A tree with the supervisor shell but no python executable is abandoned. If
    the implementation ever matches the shell's text, this returns [] and the
    check silently stops firing — the exact way the first version was wrong.
    """
    supervisor_only = f"38812 38824 20:58:42 {MAKE} factory\n38812 38902 20:58:41 {_SUPERVISOR}\n"
    assert _abandoned_factory_groups(_ps(supervisor_only)) == ["38812"]


def test_multiple_abandoned_groups_are_all_reported_sorted() -> None:
    second = _ABANDONED.replace("38812", "37608").replace("38", "37")
    out = _ps(_ABANDONED, second, _HEALTHY)
    assert _abandoned_factory_groups(out) == ["37608", "38812"]


def test_malformed_rows_do_not_crash_the_sweep() -> None:
    assert _abandoned_factory_groups(_ps("garbage\n", "\n", "1\n")) == []


def test_empty_input_is_empty() -> None:
    """Anti-vacuity floor: a sweep that returns [] for everything would pass
    every test above except the positives — this pins that [] here is the
    absence of trees, not a predicate that never matches."""
    assert _abandoned_factory_groups("") == []
