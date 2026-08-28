"""Observe what a conformance run actually does, instead of parsing what it says (#11706).

``test_vitals_conformance_seam`` reads source: which clients a file imports,
which binaries appear in a spawn's argv. That is a floor, and #11706 recorded
the residuals it cannot reach — an argv assembled from non-literals, a helper
that does the spawning, an orchestrator whose *configuration* is what reaches
out. It also recorded the opposite error, the one that costs the most: three
spawn sites whose argv names a network binary the test never executes, because
the primitive underneath is monkeypatched or the runner is injected. A parser
reads the call; it cannot read what the call resolves to.

This module reads the resolution. It arms a :func:`sys.addaudithook` hook in a
child process and watches the interpreter's own events — ``socket.connect``,
``socket.sendto``, ``subprocess.Popen``, ``os.exec``/``spawn``/``system`` — so
a faked spawn is simply *not observed* and a real one is, whatever the source
looked like. That is what lets the waiver list go to zero: an exception nobody
has to write down.

Two things it deliberately does NOT do, both covered by the kernel-level half
of the lane (``scripts/offline_egress_lane.sh``):

- see inside a child process. ``git fetch origin`` is observed as a spawn of
  ``git``; whether *it* opened a socket happens in another address space.
- see a network reach that never crosses a Python audit event (a C extension
  calling ``connect(2)`` directly).

The vocabulary is not re-typed here. ``NETWORK_CAPABLE_BINARIES`` comes from
``vitals_conformance_registry`` and ``argv_tokens``/``remote_hosts`` from
``conformance_offline_scan``, so the runtime side and the static side cannot
drift into reading the same argv two different ways.
"""

from __future__ import annotations

import ipaddress
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from tests.architecture.conformance_offline_scan import argv_tokens, remote_hosts
from tests.architecture.vitals_conformance_registry import NETWORK_CAPABLE_BINARIES

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

__all__ = [
    "OBSERVE_ENV",
    "REPORT_ENV",
    "EgressBlocked",
    "LaneResult",
    "Violation",
    "classify_argv",
    "is_local_address",
    "run_under_guard",
]

#: Set in the CHILD's environment only. Its presence is what arms the hook, so
#: importing this module in the parent — to call :func:`run_under_guard` — is
#: inert. An audit hook cannot be uninstalled, so arming one by accident in the
#: process that runs the whole suite would be unfixable for that process.
REPORT_ENV: Final = "HF_EGRESS_REPORT"

#: Record a reach instead of refusing it. There is exactly one caller —
#: ``scripts/check_egress_exclusions.py``, which asks whether a file registered
#: as *already reaching the network* still does. Refusing there would answer a
#: different question: the file would fail early and stop before its later
#: reaches, and the entry would look narrower than it is.
#:
#: Observing rather than blocking is a real weakening, so it is a separate
#: switch with one user rather than a default anything can drift into, and the
#: negative controls pin BLOCKING specifically — a lane that had silently
#: degraded to observe-only would redden them.
OBSERVE_ENV: Final = "HF_EGRESS_OBSERVE"

#: How many observed spawns the report carries. The count is always exact; the
#: list is evidence, and evidence does not need to be 1588 entries long.
_MAX_RECORDED: Final = 400


class EgressBlocked(RuntimeError):
    """Raised at the reach, in the process that made it.

    Raising rather than only recording is deliberate: it names the test in a
    traceback at the moment it happens. The session report is kept as well,
    because a broad ``except`` in the test under observation would otherwise
    swallow the only evidence.
    """


@dataclass(frozen=True, slots=True)
class Violation:
    """One observed reach out of the checkout."""

    kind: str
    """``connect`` or ``spawn``."""

    detail: str
    """Human-readable. For reading, never for asserting."""

    subjects: tuple[str, ...]
    """WHAT made it a violation: the network binaries and hosts named, or the
    address connected to. Structured because the alternative is asserting on
    the prose, and a test that greps a rendered message for ``github.com`` both
    breaks when the wording changes and reads, correctly, as incomplete URL
    sanitisation to anything scanning for it."""

    where: str
    """The pytest nodeid that was running, or ``<session>`` outside a test."""

    def describe(self) -> str:
        return f"{self.where} {self.kind}: {self.detail}"


@dataclass(frozen=True, slots=True)
class LaneResult:
    """What a guarded child process did."""

    returncode: int
    tests_run: int
    spawns: int
    connects: int
    binaries: tuple[str, ...]
    """Basenames actually spawned. The subject proof: a run that spawned
    nothing at all is indistinguishable, from the violation list alone, from a
    run that spawned nothing *bad*."""

    violations: tuple[Violation, ...]
    observed: tuple[tuple[str, str], ...]
    """``(nodeid, argv)`` for the first :data:`_MAX_RECORDED` spawns."""

    output: str


# --------------------------------------------------------------------------
# Classification — shared by the hook and by the tests that pin it
# --------------------------------------------------------------------------


def is_local_address(address: object) -> bool:
    """Is *address* somewhere this machine can reach without a network?

    Everything the asyncio machinery needs is local by this rule and none of it
    is a special case: ``socket.socketpair()`` raises no ``connect`` event at
    all (measured — the Unix implementation is the ``socketpair(2)`` syscall,
    not a bind/connect dance), an ``AF_UNIX`` connect carries a filesystem path
    rather than a tuple, and the event loop's self-pipe is a socketpair. So the
    naive fear that blocking sockets breaks the harness does not survive
    contact: what blocking ``--disable-socket``-style at the *constructor*
    would break, blocking at ``connect`` does not.

    Link-local is NOT local. ``169.254.169.254`` is the cloud metadata service,
    which is the one address where "it is not routable off the host" and "it is
    not a remote service" come apart.
    """
    if isinstance(address, str | bytes | bytearray | os.PathLike):
        return True  # AF_UNIX pathname, or an abstract namespace socket.
    if not isinstance(address, tuple) or not address:
        return True  # AF_NETLINK, AF_CAN, AF_PACKET: not IP egress.
    host = address[0]
    if isinstance(host, bytes | bytearray):
        host = bytes(host).decode("utf-8", "replace")
    if not isinstance(host, str):
        return True
    if host in {"", "localhost"}:
        return True
    try:
        parsed = ipaddress.ip_address(host.strip("[]").split("%")[0])
    except ValueError:
        # A NAME reached ``connect``. Nothing resolves it locally, so it is a
        # destination by construction.
        return False
    return parsed.is_loopback or parsed.is_unspecified


def classify_argv(argv: Sequence[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """``(network binaries named, remote hosts named)`` for a real argv.

    The same two rules the static scanner applies to argv *literals*, applied
    to the argv a process was actually handed. Reusing the tokeniser is the
    point: ``argv_tokens`` is what makes ``/usr/bin/curl`` and ``curl`` the
    same answer on both sides.
    """
    tokens = argv_tokens(argv)
    binaries = tuple(sorted(set(tokens) & NETWORK_CAPABLE_BINARIES))
    return binaries, tuple(remote_hosts(" ".join(argv)))


def _as_argv(value: object) -> list[str]:
    if isinstance(value, str | bytes | bytearray | os.PathLike):
        value = [value]
    if not isinstance(value, list | tuple):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, bytes | bytearray):
            out.append(bytes(item).decode("utf-8", "replace"))
        elif isinstance(item, os.PathLike):
            out.append(os.fspath(item))
        elif isinstance(item, str):
            out.append(item)
    return out


#: ``(event, index of the argv argument)``. ``os.system`` carries a shell
#: string rather than an argv, which ``_as_argv`` wraps into one; the tokeniser
#: splits on shell separators, so ``sh -c 'curl x | wget y'`` reads as both.
_SPAWN_EVENTS: Final[dict[str, int]] = {
    "subprocess.Popen": 1,
    "os.exec": 1,
    "os.posix_spawn": 1,
    "os.spawn": 2,
    "os.system": 0,
}


# --------------------------------------------------------------------------
# The hook itself (child process only)
# --------------------------------------------------------------------------


class _Recorder:
    def __init__(self, *, block: bool = True) -> None:
        self.block = block
        self.where = "<session>"
        self.tests_run = 0
        self.spawns = 0
        self.connects = 0
        self.binaries: set[str] = set()
        self.violations: list[Violation] = []
        self.observed: list[tuple[str, str]] = []

    def hook(self, event: str, args: tuple[Any, ...]) -> None:
        if event in {"socket.connect", "socket.sendto"}:
            self._connect(event, args)
            return
        index = _SPAWN_EVENTS.get(event)
        if index is not None:
            self._spawn(args, index)

    def _connect(self, event: str, args: tuple[Any, ...]) -> None:
        # Both events carry ``(socket, address)``. Measured, not assumed: an
        # earlier draft read ``sendto`` at index 2 on the guess that the payload
        # came first, which made every UDP reach invisible while the hook went
        # on looking armed. That is the exact failure class this module exists
        # to catch, so `test_the_guard_fails_a_run_that_sends_a_udp_datagram`
        # pins the index rather than the intent.
        if len(args) <= 1:
            return
        address = args[1]
        if is_local_address(address):
            return
        self.connects += 1
        host = address[0] if isinstance(address, tuple) and address else address
        self._raise(
            Violation("connect", f"{event} -> {address!r}", (str(host),), self.where)
        )

    def _spawn(self, args: tuple[Any, ...], index: int) -> None:
        if len(args) <= index:
            return
        argv = _as_argv(args[index])
        if not argv:
            return
        self.spawns += 1
        self.binaries.add(Path(argv[0]).name)
        if len(self.observed) < _MAX_RECORDED:
            self.observed.append((self.where, " ".join(argv)))
        binaries, hosts = classify_argv(argv)
        if not binaries and not hosts:
            return
        named = f"binaries {list(binaries)}" if binaries else ""
        reached = f"hosts {list(hosts)}" if hosts else ""
        reason = " and ".join(part for part in (named, reached) if part)
        self._raise(
            Violation("spawn", f"{argv} — {reason}", (*binaries, *hosts), self.where)
        )

    def _raise(self, violation: Violation) -> None:
        self.violations.append(violation)
        if not self.block:
            return
        raise EgressBlocked(
            f"{violation.describe()}\nA conformance check must be answerable "
            "offline from a clean checkout (docs/standards/vitals_conformance/)."
        )

    def report(self) -> dict[str, Any]:
        return {
            "tests_run": self.tests_run,
            "spawns": self.spawns,
            "connects": self.connects,
            "binaries": sorted(self.binaries),
            "violations": [
                {
                    "kind": v.kind,
                    "detail": v.detail,
                    "subjects": list(v.subjects),
                    "where": v.where,
                }
                for v in self.violations
            ],
            "observed": [list(pair) for pair in self.observed],
        }


_RECORDER: _Recorder | None = None


def _arm() -> _Recorder:
    global _RECORDER  # noqa: PLW0603 - an audit hook is process-global by nature
    if _RECORDER is None:
        _RECORDER = _Recorder(block=os.environ.get(OBSERVE_ENV) != "1")
        sys.addaudithook(_RECORDER.hook)
    return _RECORDER


if os.environ.get(REPORT_ENV):
    # Armed at IMPORT, not at ``pytest_configure``: ``-p`` plugins are imported
    # before conftest collection, and a reach during collection is still a
    # reach.
    _arm()


# --------------------------------------------------------------------------
# pytest plugin surface (child process only)
# --------------------------------------------------------------------------


def pytest_runtest_logstart(nodeid: str, location: object) -> None:  # noqa: ARG001
    if _RECORDER is not None:
        _RECORDER.where = nodeid


def pytest_runtest_logreport(report: Any) -> None:
    if _RECORDER is not None and getattr(report, "when", None) == "call":
        _RECORDER.tests_run += 1


def pytest_sessionfinish(session: object, exitstatus: object) -> None:  # noqa: ARG001
    destination = os.environ.get(REPORT_ENV)
    if _RECORDER is None or not destination:
        return
    Path(destination).write_text(json.dumps(_RECORDER.report()), encoding="utf-8")


# --------------------------------------------------------------------------
# Parent process: run something under the guard and read what it did
# --------------------------------------------------------------------------

#: Inherited pytest options would put the child under xdist or coverage, which
#: changes both the process tree it spawns and the report it writes.
_DROPPED_ENV: Final = ("PYTEST_ADDOPTS", "PYTEST_CURRENT_TEST", "PYTEST_XDIST_WORKER")

_PLUGIN: Final = "tests.architecture.egress_guard"


def run_under_guard(
    targets: Sequence[str],
    *,
    repo_root: Path,
    report_dir: Path,
    timeout: float = 900.0,
    block: bool = True,
) -> LaneResult:
    """Run pytest over *targets* in a child process with the hook armed.

    A missing report is a hard failure rather than an empty one: a child that
    died before ``pytest_sessionfinish`` observed nothing, and "observed
    nothing" must never read the same as "observed nothing wrong".
    """
    report_path = report_dir / "egress-report.json"
    report_path.unlink(missing_ok=True)

    env = dict(os.environ)
    for key in _DROPPED_ENV:
        env.pop(key, None)
    env["PYTHONPATH"] = os.pathsep.join((str(repo_root), str(repo_root / "src")))
    env[REPORT_ENV] = str(report_path)
    env.pop(OBSERVE_ENV, None)
    if not block:
        env[OBSERVE_ENV] = "1"

    command = [
        sys.executable,
        "-m",
        "pytest",
        *targets,
        "-p",
        _PLUGIN,
        "-p",
        "no:cacheprovider",
        "-p",
        "no:randomly",
        "-q",
        "--no-header",
        "-o",
        "addopts=",
    ]
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
        command,
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    output = f"{completed.stdout}\n{completed.stderr}"

    if not report_path.is_file():
        raise AssertionError(
            "the egress lane produced no report. The guarded child exited "
            f"{completed.returncode} without reaching pytest_sessionfinish, so "
            "it observed nothing — which is not the same as observing nothing "
            f"wrong. Output:\n{output[-4000:]}"
        )
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    return LaneResult(
        returncode=completed.returncode,
        tests_run=int(payload["tests_run"]),
        spawns=int(payload["spawns"]),
        connects=int(payload["connects"]),
        binaries=tuple(payload["binaries"]),
        violations=tuple(
            Violation(
                item["kind"],
                item["detail"],
                tuple(item["subjects"]),
                item["where"],
            )
            for item in payload["violations"]
        ),
        observed=tuple((pair[0], pair[1]) for pair in payload["observed"]),
        output=output,
    )
