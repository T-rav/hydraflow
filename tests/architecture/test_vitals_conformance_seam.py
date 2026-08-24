"""A conformance claim may not depend on an external data plane (#11688).

The rule is in ``docs/standards/vitals_conformance/README.md``. This is what
makes it enforceable rather than a convention, because a convention is exactly
the thing that goes vacuous: the seam erodes the easy way, when someone wires a
conformance check to read a metric from the vitals plane *because it is already
there*, and "do the articles hold" quietly becomes "the vendor's dashboard said
so."
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from tests.architecture.vitals_conformance_registry import (
    CONFORMANCE_ROOTS,
    ClaimKind,
    registered_claims,
    repo_root,
)

_REPO = repo_root()

#: Clients that can ONLY mean a remote service. Importing one into a
#: conformance check means the rule is answered by asking a server.
#:
#: ``httpx``/``socket``/``urllib`` are deliberately ABSENT. The first version of
#: this set included them and flagged three regression tests that build an
#: in-process ``httpx.MockTransport`` against RFC-2606 ``.test`` hostnames —
#: entirely offline. "Imports an HTTP library" is not "depends on a network";
#: conflating them would have made the rule mean something it does not, and the
#: allow-list needed to keep it green would have grown until it was the rule.
_REMOTE_CLIENTS: frozenset[str] = frozenset(
    {
        "requests",
        "aiohttp",
        "boto3",
        "botocore",
        "swamp",
        "ftplib",
        "telnetlib",
        "smtplib",
        "xmlrpc",
    }
)

#: Kept for the negative control below, NOT used as a sweep.
#:
#: A URL-literal sweep was the second thing tried and it is also wrong: fixture
#: data legitimately contains ``https://github.com/...`` and sample payloads
#: name hosts the test never contacts. Both proxies (imports-an-HTTP-library,
#: names-a-URL) push toward an allow-list to stay green, and an allow-list that
#: grows until it is the rule is the fail-open shape this standard exists to
#: prevent. What remains is the check with zero false positives: importing a
#: client that can ONLY mean a remote service.
#:
#: Hosts that are not a remote service: loopback, and the TLDs RFC 2606 reserves
#: precisely so a test can name a host it will never contact.
_LOCAL_HOST_RE = re.compile(
    r"^(?:localhost|127\.0\.0\.1|\[::1\]|0\.0\.0\.0)(?::\d+)?$|"
    r"\.(?:test|invalid|example|localhost)$",
    re.IGNORECASE,
)

_URL_RE = re.compile(r"https?://([^/\s\"']+)")

# There is deliberately no allow-list here. One was written — a single entry
# exempting THIS file, on the theory that verifying "nothing reaches the
# network" requires naming what that means. It does not: the names live in
# ``_REMOTE_CLIENTS`` as strings and in the negative control as source written
# to ``tmp_path``, never as an import, so the exemption was a no-op that
# exempted the one file whose job is the rule. A no-op exemption is worse than
# none, because the day this file did import a remote client the sweep would
# have stayed green. It is swept like everything else.


def _conformance_files() -> list[Path]:
    """Every conformance root, PLUS any registered conformance claim outside one.

    A claim classified conformance is held to the offline rule wherever it
    lives; scoping the sweep to the roots alone would have let
    ``tests/test_loop_credit_reraise_completeness.py`` register as conformance
    and never be swept.
    """
    out: list[Path] = []
    for root in CONFORMANCE_ROOTS:
        out.extend(sorted((_REPO / root).rglob("*.py")))
    for claim in registered_claims():
        if claim.kind is ClaimKind.CONFORMANCE:
            path = _REPO / claim.path
            if path.is_file() and path not in out:
                out.append(path)
    return out


def _imported_roots(path: Path) -> set[str]:
    """Top-level package of every import in *path*, at any nesting depth."""
    try:
        tree = ast.parse(path.read_text(errors="replace"), filename=str(path))
    except SyntaxError:  # pragma: no cover - a broken test fails elsewhere
        return set()
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_the_registry_is_not_empty() -> None:
    """Every property below runs over this; an empty registry is a silent pass."""
    claims = registered_claims()
    assert claims, "no claims registered — every seam property is vacuous"
    kinds = {claim.kind for claim in claims}
    assert kinds == {ClaimKind.VITALS, ClaimKind.CONFORMANCE}, (
        f"only {kinds} registered — a seam with one side is not a seam"
    )


@pytest.mark.parametrize("claim", registered_claims(), ids=lambda c: c.name)
def test_every_registered_claim_resolves_on_disk(claim: object) -> None:
    """A claim about a file that is gone is not a claim (#11673's lesson)."""
    assert (_REPO / claim.path).exists(), (  # type: ignore[attr-defined]
        f"{claim.name} points at {claim.path}, which does not exist. "  # type: ignore[attr-defined]
        "Re-point it or drop it — a dead entry classifies nothing."
    )


def test_the_conformance_roots_are_real_and_populated() -> None:
    for root in CONFORMANCE_ROOTS:
        found = list((_REPO / root).rglob("*.py"))
        assert found, f"{root} has no Python files — the sweep below is vacuous"


def test_no_conformance_check_imports_a_remote_client() -> None:
    """The load-bearing property, and the honest limit of a static check.

    A conformance check must be answerable offline from a clean checkout. If it
    imports a client that can only mean a remote service, the rule it claims to
    enforce is one outage away from being unanswerable — and an assurance seat
    auditable only through somebody else's uptime is not an assurance seat.

    This catches *dependence on a service*, not *use of HTTP*: see the comment
    on ``_REMOTE_CLIENTS`` for the two proxies that were tried and rejected.
    Statically this is as far as it goes honestly; proving the suite actually
    runs with no network is a CI-lane concern, recorded in the standard.
    """
    offenders: list[str] = []
    for path in _conformance_files():
        rel = str(path.relative_to(_REPO))
        reached = _imported_roots(path) & _REMOTE_CLIENTS
        if reached:
            offenders.append(f"{rel} imports remote client(s) {sorted(reached)}")

    assert not offenders, (
        "conformance checks must run offline (docs/standards/vitals_conformance/). "
        "These reach a network:\n  " + "\n  ".join(offenders)
    )


def _remote_hosts(path: Path) -> list[str]:
    """URL hosts in *path* that are neither loopback nor an RFC-2606 sentinel."""
    text = path.read_text(errors="replace")
    return sorted({h for h in _URL_RE.findall(text) if not _LOCAL_HOST_RE.search(h)})


def test_the_remote_client_detector_actually_fires(tmp_path: Path) -> None:
    """Negative control. The sweep passes today, so prove it can fail.

    Without this, deleting the detector's body leaves a green test that has
    never observed a violation — the shape this whole standard exists to stop.
    """
    victim = tmp_path / "test_victim.py"
    victim.write_text("import boto3\n\n\ndef test_x():\n    assert boto3\n")
    assert _imported_roots(victim) & _REMOTE_CLIENTS == {"boto3"}

    nested = tmp_path / "test_nested.py"
    nested.write_text("def test_x():\n    import swamp\n\n    assert swamp\n")
    assert _imported_roots(nested) & _REMOTE_CLIENTS == {"swamp"}, (
        "a deferred import inside a function still reaches the service"
    )

    remote = tmp_path / "test_remote.py"
    remote.write_text('URL = "https://vitals.example.com/api"\n')
    assert _remote_hosts(remote) == ["vitals.example.com"]

    # The three shapes that must NOT fire: an in-process mock transport, a
    # loopback address, and an RFC-2606 sentinel host.
    clean = tmp_path / "test_clean.py"
    clean.write_text(
        "import httpx\n"
        'A = "https://zai.test/v1"\n'
        'B = "http://127.0.0.1:8000/health"\n'
        'C = "https://upstream.invalid/x"\n'
    )
    assert not (_imported_roots(clean) & _REMOTE_CLIENTS)
    assert _remote_hosts(clean) == []


def test_a_vitals_claim_is_not_held_to_the_offline_rule() -> None:
    """The seam has two sides, and the point is that vitals MAY externalise.

    Two assertions, because the original made one and gave the other's reason.

    It checked the path PREFIX and justified it as "it would be swept by the
    offline rule" — which is false for six of the seven vitals claims: they are
    ``.yaml`` files, ``_conformance_files()`` globs ``*.py``, and a ``.yaml``
    under ``tests/architecture`` would never be swept whatever the prefix says.
    A guard whose stated reason does not describe its subject passes for a
    reason nobody can check, which is how it goes vacuous unnoticed.

    So the prefix survives as what it actually is — a FILING rule, vitals do
    not live under a conformance root — and the claim its reason made is
    asserted directly against the sweep. The second is the load-bearing one and
    is strictly wider: ``_conformance_files()`` also pulls in registered
    conformance claims from outside the roots, which no prefix check can see.
    """
    vitals = [c for c in registered_claims() if c.kind is ClaimKind.VITALS]
    assert vitals, "no vitals registered — nothing may be externalised, which is wrong"
    swept = set(_conformance_files())
    for claim in vitals:
        assert not any(claim.path.startswith(root) for root in CONFORMANCE_ROOTS), (
            f"{claim.name} is registered as vitals but is filed under a "
            f"conformance root ({claim.path}). Vitals live elsewhere."
        )
        assert (_REPO / claim.path) not in swept, (
            f"{claim.name} is registered as vitals but ({claim.path}) is inside "
            "the offline sweep; it would be held to the conformance rule."
        )


def test_every_claim_records_what_breaks_without_the_plane() -> None:
    """The classification rule is 'what breaks if the plane is down'. A claim
    that cannot answer that has not been classified, only labelled."""
    for claim in registered_claims():
        assert len(claim.why) > 20, f"{claim.name} has no real rationale"


def test_the_standard_exists_and_states_the_rule() -> None:
    """The enforcement and the prose must not drift apart."""
    standard = _REPO / "docs/standards/vitals_conformance/README.md"
    assert standard.exists(), "the rule has no written home"
    text = standard.read_text()
    assert "offline" in text
    assert "vitals" in text.lower() and "conformance" in text.lower()
