"""#11706: the egress guard's assumptions about CPython's audit events.

``tests/architecture/test_conformance_egress_lane.py`` pins what the guard
DOES. This pins what the guard BELIEVES about the interpreter underneath it,
and the two are different subjects: an architecture control catches a
regression in our code, and nothing catches a regression in an assumption we
never wrote down.

Both properties here were live defects during #11706's build.

**The address is at index 1.** ``socket.sendto``'s audit event carries
``(socket, address)`` — the payload is not in it at all. The first draft of
``egress_guard`` read index 2, on the reasonable guess that the bytes came
first. Nothing reddened: the hook stayed armed, the guarded run reported no
violation, and every UDP reach in the conformance roots was invisible. **A
guard that is on and silent is the exact failure this lane exists to catch**,
reproduced inside the lane. It was found by pinning the observation instead of
the intention, which is what this file does.

**``socket.socketpair()`` raises no connect event.** That measurement is what
made the lane possible at all. The previous author declined it because
``pytest-socket --disable-socket`` breaks asyncio, and that was correct about
``pytest-socket`` and wrong about the problem: blocking at the socket
CONSTRUCTOR breaks the event loop's self-pipe, blocking at ``connect`` does
not. If a future CPython starts emitting a connect event for socketpair, the
guard would flag every asyncio event loop in the repo, the lane would be
switched off within a day, and the objection would look like it had been right
all along. Better to learn it from this test.

The probe runs in a child process because ``sys.addaudithook`` cannot be
removed: arming one in the pytest worker would leave every later test paying
for it. It needs no network — an audit event fires BEFORE the syscall, so the
unreachable address is never actually contacted and this passes inside the
egress-blocked lane exactly as it does on a laptop.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tests.architecture.egress_guard import is_local_address

#: Reserved for documentation (RFC 5737 TEST-NET-1) precisely so it names a
#: destination nothing routes to. The datagram is never sent — the audit hook
#: observes the call and the syscall then fails — but a documentation address
#: makes that a fact about the code rather than a fact about the network.
_UNREACHABLE_HOST = "192.0.2.1"
_UNREACHABLE_PORT = 9

_PROBE = f'''
import asyncio, json, socket, sys

events = []
phase = ["setup"]


def hook(event, args):
    if event in ("socket.connect", "socket.sendto"):
        events.append(
            {{
                "phase": phase[0],
                "event": event,
                "nargs": len(args),
                "arg1": list(args[1]) if isinstance(args[1], tuple) else None,
            }}
        )


sys.addaudithook(hook)

# --- phase: socketpair. The asyncio self-pipe, and the raw primitive. -------
phase[0] = "socketpair"
left, right = socket.socketpair()
left.close()
right.close()


async def _noop():
    return None


asyncio.run(_noop())

# --- phase: connect. A real loopback round trip. ----------------------------
phase[0] = "connect"
server = socket.socket()
server.bind(("127.0.0.1", 0))
server.listen(1)
with socket.create_connection(server.getsockname(), timeout=5):
    pass
server.close()

# --- phase: sendto. Connectionless, to somewhere nothing routes. ------------
phase[0] = "sendto"
udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    udp.sendto(b"x", ("{_UNREACHABLE_HOST}", {_UNREACHABLE_PORT}))
except OSError:
    pass  # the point is the audit event, which already fired
finally:
    udp.close()

print(json.dumps(events))
'''


def _probe(tmp_path: Path) -> list[dict[str, object]]:
    script = tmp_path / "audit_probe.py"
    script.write_text(_PROBE, encoding="utf-8")
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    return json.loads(completed.stdout)


def test_socketpair_and_the_asyncio_self_pipe_raise_no_connect_event(
    tmp_path: Path,
) -> None:
    """The measurement the whole lane rests on.

    If this ever reddens, the guard must stop blocking at ``connect`` before
    anyone notices via a suite that will not run.
    """
    quiet = [event for event in _probe(tmp_path) if event["phase"] == "socketpair"]
    assert quiet == [], (
        "socket.socketpair() or the asyncio event loop now raises a connect "
        f"audit event: {quiet}. egress_guard blocks non-local connects, so this "
        "makes the guard fire on the harness itself rather than on egress — the "
        "exact breakage that made `pytest-socket --disable-socket` unusable "
        "here, arriving through the door we chose to avoid it."
    )


def test_sendto_carries_its_address_at_index_one_and_has_no_index_two(
    tmp_path: Path,
) -> None:
    """The defect, pinned where it actually lives: in CPython's event, not ours.

    ``nargs == 2`` is the load-bearing half. The draft that read ``args[2]``
    did not crash — it hit ``len(args) <= index`` and returned early, every
    time, silently. Asserting only that index 1 holds the address would still
    pass against a three-argument event where index 2 also existed.
    """
    sent = [event for event in _probe(tmp_path) if event["event"] == "socket.sendto"]
    assert len(sent) == 1, f"expected one sendto event, got {sent}"
    assert sent[0]["nargs"] == 2, (
        f"socket.sendto's audit event now carries {sent[0]['nargs']} arguments "
        "rather than (socket, address). egress_guard reads the address at index "
        "1; check that is still where it is."
    )
    assert sent[0]["arg1"] == [_UNREACHABLE_HOST, _UNREACHABLE_PORT]


def test_connect_carries_its_address_at_index_one(tmp_path: Path) -> None:
    """The same layout for the other event the guard watches."""
    connected = [
        event for event in _probe(tmp_path) if event["event"] == "socket.connect"
    ]
    assert connected, "no connect event for a real loopback round trip"
    assert connected[0]["nargs"] == 2
    assert connected[0]["arg1"] is not None
    assert connected[0]["arg1"][0] == "127.0.0.1"


def test_the_guard_classifies_the_addresses_the_interpreter_actually_hands_it(
    tmp_path: Path,
) -> None:
    """Close the loop: the recorded layout and the classifier must agree.

    Reading the right index is worth nothing if what sits there is classified
    wrongly, and classifying correctly is worth nothing if it is read from the
    wrong index. Asserting them separately leaves the join untested, and the
    join is where the silent failure lived.
    """
    events = _probe(tmp_path)
    by_event = {event["event"]: event for event in events}
    remote = by_event["socket.sendto"]["arg1"]
    local = by_event["socket.connect"]["arg1"]
    assert remote is not None and local is not None

    assert not is_local_address(tuple(remote)), (
        f"the guard treats {remote} as local, so a UDP reach there would be "
        "recorded as harmless."
    )
    assert is_local_address(tuple(local)), (
        f"the guard treats {local} as remote. Loopback is how the conformance "
        "roots talk to their own test servers; flagging it makes the lane fire "
        "on the suite instead of on egress."
    )
