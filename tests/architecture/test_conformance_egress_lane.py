"""The egress-blocked lane, and the controls that stop it lying (#11706).

``test_vitals_conformance_seam`` reads source. The standard records, in its own
words, what source cannot answer: an orchestrator whose *configuration* reaches
out, a ``git fetch`` whose remote is set elsewhere, an argv assembled from
non-literals, a spawn performed by a helper the check calls. Every one of those
is a runtime fact, and the answer to a runtime fact is to run the thing and
watch.

Two mechanisms, and the split matters:

* :mod:`tests.architecture.egress_guard` arms a ``sys.addaudithook`` hook in a
  child process. It sees ``socket.connect``, ``socket.sendto`` and every spawn
  primitive, so it can NAME the test that reached and read the argv a process
  was actually handed. It cannot see inside a child process.
* ``scripts/offline_egress_lane.sh`` verifies that the surrounding process tree
  has no route off the host. That covers what the hook cannot — a ``gh`` that
  opens its own socket, a ``mkdocs`` plugin fetching Google Fonts — and it is
  the half that runs in CI.

**What this lane does not cover, stated here rather than implied.** The hook
observes Python-level events, so a C extension calling ``connect(2)`` directly
is invisible to it; only the namespace catches that, and only in CI on Linux.
The namespace half does not run on macOS at all, so a developer box gets the
hook and not the kernel. And three conformance files are registered in
``EGRESS_LANE_EXCLUSIONS`` because they really do reach the network today: the
lane does not run those, ``scripts/check_egress_exclusions.py`` proves each one
still needs to be excluded, and the count is shrink-only.

The measured reason none of this needed ``pytest-socket``-style blanket socket
blocking: ``socket.socketpair()`` — which is what the asyncio event loop's
self-pipe is — raises no ``connect`` audit event at all, and the ~1500 ``git``
spawns the conformance roots make against ``tmp_path`` repos name no host, so
they are not flagged by either rule. Blocking at ``connect`` rather than at the
socket constructor is what makes the difference, and
``test_the_guard_leaves_local_machinery_alone`` is the pin.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tests.architecture.egress_guard import run_under_guard
from tests.architecture.vitals_conformance_registry import (
    CONFORMANCE_ROOTS,
    EGRESS_LANE_EXCLUSIONS,
    repo_root,
)

_REPO = repo_root()
_LANE_SCRIPT = _REPO / "scripts" / "offline_egress_lane.sh"
_EXCLUSION_CHECKER = _REPO / "scripts" / "check_egress_exclusions.py"
_WORKFLOW = _REPO / ".github" / "workflows" / "ci.yml"

# The child sources below are DATA. They are written to ``tmp_path`` and never
# appear inside a spawn call's argv here, which is why the static scanner does
# not flag this file for naming ``curl`` and a github URL: it reads argv nodes,
# not string constants. That is the same reason the seam's own negative
# controls write their fixtures to disk.
_REACHES_A_HOST = """
import socket


def test_reaches_out():
    socket.create_connection(("1.1.1.1", 443), timeout=5)
"""

_SPAWNS_A_NETWORK_BINARY = """
import subprocess


def test_spawns_a_transfer_tool():
    subprocess.run(["curl", "-sS", "http://example.org/x"], check=False)
"""

_NAMES_A_HOST_IN_AN_ARGV = """
import subprocess


def test_clones_from_a_forge(tmp_path):
    subprocess.run(
        ["git", "clone", "https://github.com/octocat/Hello-World", str(tmp_path / "c")],
        check=False,
    )
"""

_SENDS_A_UDP_DATAGRAM = """
import socket


def test_sends_a_datagram():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(b"x", ("1.1.1.1", 9))
    finally:
        sock.close()
"""

_ONLY_LOCAL_MACHINERY = """
import asyncio
import socket
import subprocess
import sys


def test_socketpair_and_local_spawns_are_not_egress():
    left, right = socket.socketpair()
    left.close()
    right.close()

    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    with socket.create_connection(server.getsockname(), timeout=5):
        pass
    server.close()

    subprocess.run(["git", "--version"], check=True, capture_output=True)

    async def _spawn():
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", "pass", stdout=asyncio.subprocess.PIPE
        )
        await proc.communicate()

    asyncio.run(_spawn())
"""

_COLLECTS_NOTHING = """
def helper_not_a_test():
    return 1
"""


def _child(tmp_path: Path, name: str, source: str) -> str:
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return str(path)


def _run_lane_script(*args: str, env_python: str | None = None) -> tuple[int, str]:
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin"}
    if env_python is not None:
        env["HF_EGRESS_PYTHON"] = env_python
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["bash", str(_LANE_SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
        env=env,
    )
    return completed.returncode, f"{completed.stdout}\n{completed.stderr}"


def _canary_stub(tmp_path: Path, name: str, verdicts: str) -> str:
    """A stand-in for the canary interpreter that reports *verdicts* verbatim.

    The lane script's decision — isolated, not isolated, or loopback broken — is
    the part that must never be wrong, and on a networked machine only one of
    its three branches can be reached for real. Feeding it verdicts exercises
    all three deterministically and offline.
    """
    stub = tmp_path / name
    stub.write_text(
        "#!/bin/sh\ncat >/dev/null\n"
        + "".join(
            f"printf '%s\\n' '{line}'\n" for line in verdicts.splitlines() if line
        ),
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return str(stub)


# --------------------------------------------------------------------------
# The guard fires
# --------------------------------------------------------------------------


def test_the_guard_fails_a_run_that_opens_a_remote_connection(tmp_path: Path) -> None:
    """Requirement one: the lane must fail when something genuinely reaches out.

    The reach never completes — the hook raises inside ``socket.connect``
    before the syscall — which is why this control is decisive on a machine
    with no network as well as on one with. It is testing the observer, not the
    internet.
    """
    result = run_under_guard(
        [_child(tmp_path, "test_reach.py", _REACHES_A_HOST)],
        repo_root=_REPO,
        report_dir=tmp_path,
    )
    kinds = {violation.kind for violation in result.violations}
    assert "connect" in kinds, (
        "the guard did not notice an outbound connection. Everything else in "
        f"this lane is downstream of that. Observed: {result.violations}"
    )
    assert result.returncode != 0, (
        "the reaching test still passed. A recorded violation that does not "
        "also fail the run is a lane nobody will act on."
    )
    assert "1.1.1.1" in result.violations[0].detail
    assert "test_reaches_out" in result.violations[0].where


def test_the_guard_fails_a_run_that_sends_a_udp_datagram(tmp_path: Path) -> None:
    """Connectionless egress, and the index this hook reads it at.

    TCP is the obvious shape and ``socket.connect`` is the obvious event, which
    is how a draft of this guard came to read ``socket.sendto``'s address at
    the wrong tuple index — it carries ``(socket, address)``, not the payload
    first. Nothing reddened: the hook stayed armed, reported no violation, and
    every UDP reach was invisible. Pinning the observation rather than the
    intention is the only version of this test that would have caught it.
    """
    result = run_under_guard(
        [_child(tmp_path, "test_udp.py", _SENDS_A_UDP_DATAGRAM)],
        repo_root=_REPO,
        report_dir=tmp_path,
    )
    assert [violation.kind for violation in result.violations] == ["connect"]
    assert "1.1.1.1" in result.violations[0].detail
    assert result.returncode != 0


def test_the_guard_fails_a_run_that_spawns_a_network_binary(tmp_path: Path) -> None:
    """The residual a parser CAN see, re-proved where a parser cannot.

    ``curl`` in a literal argv is caught statically today. The point of proving
    it here as well is that the runtime rule reads the argv a process was
    actually handed — so it holds for the argv the static scanner declares
    itself blind to, the one assembled from variables.
    """
    result = run_under_guard(
        [_child(tmp_path, "test_spawn.py", _SPAWNS_A_NETWORK_BINARY)],
        repo_root=_REPO,
        report_dir=tmp_path,
    )
    assert [violation.kind for violation in result.violations] == ["spawn"]
    assert "curl" in result.violations[0].detail
    assert result.returncode != 0


def test_the_guard_fails_a_spawn_that_names_a_remote_host(tmp_path: Path) -> None:
    """``git`` is not on the binary list, and must still not be a way out.

    129 of the conformance roots' spawn sites are ``git`` against a throwaway
    repo under ``tmp_path``; listing ``git`` would need a ~130-entry allow-list.
    The host rule is what keeps it honest, and it has to keep being what keeps
    it honest at runtime too.
    """
    result = run_under_guard(
        [_child(tmp_path, "test_clone.py", _NAMES_A_HOST_IN_AN_ARGV)],
        repo_root=_REPO,
        report_dir=tmp_path,
    )
    assert [violation.kind for violation in result.violations] == ["spawn"]
    assert "github.com" in result.violations[0].detail
    assert result.returncode != 0


def test_the_guard_leaves_local_machinery_alone(tmp_path: Path) -> None:
    """The reason this is a lane and not ``--disable-socket``.

    A socket-constructor block breaks the harness it is meant to observe:
    asyncio's event loop builds its self-pipe from ``socket.socketpair()``, and
    the conformance roots spawn ``git`` about 1500 times. Blocking at
    ``connect`` instead costs none of that, and this is the pin — socketpair,
    a loopback round trip, a synchronous ``git``, and an asyncio subprocess, all
    in one guarded run, all clean.

    ``spawns`` is asserted for a reason: a guard that had stopped observing
    would also report no violations.
    """
    result = run_under_guard(
        [_child(tmp_path, "test_local.py", _ONLY_LOCAL_MACHINERY)],
        repo_root=_REPO,
        report_dir=tmp_path,
    )
    assert result.violations == (), (
        "the guard flagged ordinary local machinery. That is the false-positive "
        f"class that gets a lane switched off: {result.violations}"
    )
    assert result.returncode == 0, result.output[-2000:]
    assert result.spawns >= 2, (
        f"the guarded run observed {result.spawns} spawns. It should have seen "
        "git and an asyncio child; a zero here means the hook is not armed and "
        "every other assertion in this file is about nothing."
    )
    assert "git" in result.binaries


# --------------------------------------------------------------------------
# Guard the guard
# --------------------------------------------------------------------------


def test_a_guarded_run_that_observed_nothing_is_not_a_clean_run(
    tmp_path: Path,
) -> None:
    """ "Ran no tests" and "found nothing wrong" must not read the same.

    The escalation in ``test_vitals_conformance_seam`` asserts ``tests_run > 0``
    for exactly this reason. Here is the state that assertion exists to catch,
    constructed.
    """
    result = run_under_guard(
        [_child(tmp_path, "test_empty.py", _COLLECTS_NOTHING)],
        repo_root=_REPO,
        report_dir=tmp_path,
    )
    assert result.tests_run == 0
    assert result.violations == ()


def test_a_child_that_never_reported_is_a_hard_failure(tmp_path: Path) -> None:
    """A missing report must raise, not decay into an empty one.

    Pointing the run at a root with no ``tests`` package makes the child die on
    the ``-p`` import, before ``pytest_sessionfinish``. The temptation in that
    branch is to return a ``LaneResult`` with no violations, which is a lane
    that silently stops blocking anything.
    """
    with pytest.raises(AssertionError, match="produced no report"):
        run_under_guard(["-x"], repo_root=tmp_path, report_dir=tmp_path)


def test_observe_mode_records_without_refusing(tmp_path: Path) -> None:
    """The one weakening in the design, pinned so it cannot spread.

    ``check_egress_exclusions.py`` needs to watch a reach without stopping the
    run at the first one. That is strictly weaker than blocking, so it is a
    separate switch with one caller — and the controls above pin BLOCKING, so a
    lane that had drifted to observe-only would redden them rather than pass.
    """
    result = run_under_guard(
        [_child(tmp_path, "test_spawn_observed.py", _SPAWNS_A_NETWORK_BINARY)],
        repo_root=_REPO,
        report_dir=tmp_path,
        block=False,
    )
    assert [violation.kind for violation in result.violations] == ["spawn"]
    assert result.returncode == 0, (
        "observe mode refused the spawn anyway. Then it is not observe mode, "
        f"and the exclusion checker will read narrower than the truth:\n{result.output[-1500:]}"
    )


# --------------------------------------------------------------------------
# The kernel half: the lane script's own verdict
# --------------------------------------------------------------------------


def test_the_lane_script_refuses_an_environment_that_can_still_reach_out(
    tmp_path: Path,
) -> None:
    """Requirement four: a lane that stopped isolating must fail, not pass.

    This is the whole reason the script verifies rather than assumes. On a
    networked machine the real ``--verify-only`` run exercises this branch for
    free; the stub is here so it is exercised on an offline one too, which is
    precisely when a silently-not-isolating lane would be least noticeable.
    """
    stub = _canary_stub(
        tmp_path,
        "reached.sh",
        "reached\toutbound TCP to 1.1.1.1:443: REACHED\nok\tDNS: blocked\nok\tloopback connect: works",
    )
    code, output = _run_lane_script("--verify-only", env_python=stub)
    assert code == 3, output
    assert "can still reach the network" in output


def test_the_lane_script_refuses_a_namespace_with_no_loopback(tmp_path: Path) -> None:
    """The other way a lane degrades: it isolates too much.

    ``unshare --net`` hands over a namespace whose ``lo`` is down, and the
    conformance roots really do use loopback. A lane that ran anyway would fail
    the suite for a reason unrelated to egress, which is how a gate earns the
    reputation that gets it switched off.
    """
    stub = _canary_stub(
        tmp_path,
        "noloop.sh",
        "ok\toutbound TCP: blocked\nok\tDNS: blocked\nloopback\tloopback connect: BROKEN",
    )
    code, output = _run_lane_script("--verify-only", env_python=stub)
    assert code == 3, output
    assert "loopback is unusable" in output


def test_the_lane_script_accepts_a_genuinely_isolated_environment(
    tmp_path: Path,
) -> None:
    """And the third branch, so the refusals above are not the only outcome."""
    stub = _canary_stub(
        tmp_path,
        "clean.sh",
        "ok\toutbound TCP: blocked\nok\tDNS: blocked\nok\tloopback connect: works",
    )
    code, output = _run_lane_script("--verify-only", env_python=stub)
    assert code == 0, output
    assert "verified" in output


def test_the_lane_script_runs_its_three_canaries_for_real() -> None:
    """The stubs above pin the decision; this pins the canaries it decides on.

    A stubbed interpreter cannot tell you the real canaries still probe
    anything. This runs them unstubbed and requires all three verdicts, plus a
    working loopback — the one part of the answer that does not depend on
    whether this host happens to be isolated.
    """
    code, output = _run_lane_script("--verify-only")
    for probe in (
        "outbound TCP to 1.1.1.1:443",
        "DNS for github.com",
        "loopback connect",
    ):
        assert probe in output, f"the {probe!r} canary did not run:\n{output}"
    assert "loopback connect: works" in output, output
    if "REACHED" in output:
        assert code == 3, (
            "this host can reach the network and the script said the "
            f"environment was isolated. Exit {code}:\n{output}"
        )
    else:
        assert code == 0, output


# --------------------------------------------------------------------------
# The lane is actually wired in
# --------------------------------------------------------------------------


def _run_blocks() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Every ``run:`` script in ci.yml, split by whether it goes through the lane.

    Read from the parsed workflow rather than from raw text. A substring search
    over the whole file cannot tell "the lane runs this root" from "this root is
    mentioned somewhere in the file", and the second is true of a workflow where
    the lane has been quietly unwired.
    """
    workflow = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    lane: list[str] = []
    plain: list[str] = []
    for job in workflow["jobs"].values():
        for step in job.get("steps") or []:
            script = step.get("run")
            if not isinstance(script, str):
                continue
            (lane if "offline_egress_lane.sh" in script else plain).append(script)
    return tuple(lane), tuple(plain)


def test_the_workflow_runs_both_conformance_roots_through_the_lane() -> None:
    """A lane nobody runs is a script, and #11730's lesson one mechanism over.

    The scope claim this file makes at the top — "the conformance roots, minus
    the registered exclusions" — is only true while the workflow says so. If
    the arch or regression job stops going through the lane, the standard's
    "unbuilt (#11706)" line is true again and nothing else here would notice.
    """
    assert _LANE_SCRIPT.is_file(), f"{_LANE_SCRIPT} is gone"
    lane_blocks, _ = _run_blocks()
    assert lane_blocks, (
        "no ci.yml step invokes scripts/offline_egress_lane.sh. Every property "
        "in this file then describes a script that runs nowhere."
    )
    for root in CONFORMANCE_ROOTS:
        assert any(root in block for block in lane_blocks), (
            f"the conformance root {root} is never run inside the egress lane. "
            "The static checks still cover it; the residuals they declare "
            "themselves blind to do not."
        )


def test_the_workflow_excludes_exactly_the_registered_exclusions() -> None:
    """The exclusion list and the thing it excludes must travel together.

    Two individually-green edits — drop a path from the workflow's ignore list,
    leave the registry row — is how a file quietly rejoins a lane it still
    breaks, or stays out of one it no longer needs to. Both directions are
    pinned: the lane must ignore every registered path, and something outside
    the lane must still run it, or excluding it would silently drop its verdict.
    """
    lane_blocks, plain_blocks = _run_blocks()
    lane_text = "\n".join(lane_blocks)
    plain_text = "\n".join(plain_blocks)
    for exclusion in EGRESS_LANE_EXCLUSIONS:
        assert exclusion.path in lane_text, (
            f"{exclusion.path} is registered as an egress-lane exclusion but no "
            "lane step names it. Either the lane is running a file that reaches "
            "the network, or the row is stale."
        )
        assert exclusion.path in plain_text, (
            f"{exclusion.path} is excluded from the lane and run nowhere else. "
            "Excluding a file from the egress lane must not delete its ordinary "
            "verdict — that trades one gate for two."
        )
    assert any("check_egress_exclusions.py" in block for block in lane_blocks), (
        "the exclusion checker never runs inside the lane. Then "
        "EGRESS_LANE_EXCLUSIONS is a list nobody re-reads, which is the failure "
        "mode this whole standard is about — and running it outside the lane "
        "would perform the very reaches it measures."
    )
    assert _EXCLUSION_CHECKER.is_file(), f"{_EXCLUSION_CHECKER} is gone"


def test_the_exclusion_checker_refuses_to_run_outside_the_lane() -> None:
    """Observing these files outside a namespace PERFORMS the reach.

    The check exists to prove three tests still hit a real forge. Running it on
    an un-isolated box would do exactly what it is measuring — from CI, against
    someone's rate limit — so it refuses.
    """
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, str(_EXCLUSION_CHECKER)],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
        cwd=_REPO,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert completed.returncode == 2, completed.stdout + completed.stderr
    assert "refusing to run outside the lane" in completed.stderr
