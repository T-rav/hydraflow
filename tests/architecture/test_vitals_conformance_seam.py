"""A conformance claim may not depend on an external data plane (#11688).

The rule is in ``docs/standards/vitals_conformance/README.md``. This is what
makes it enforceable rather than a convention, because a convention is exactly
the thing that goes vacuous: the seam erodes the easy way, when someone wires a
conformance check to read a metric from the vitals plane *because it is already
there*, and "do the articles hold" quietly becomes "the vendor's dashboard said
so."

#11706 found the first version of this enforcement green **by luck**. It swept
673 files for a top-level import of a remote client and passed — but it parsed
one file at a time (a check that imported a local module which imported the
client was invisible) and it never looked at ``subprocess`` (a check that shells
``curl`` imports nothing at all). Neither hole had a live subject, which is the
only reason it was green. The mechanics that close them are in
``conformance_offline_scan``; the policy — which names count as a reach — stays
here and in ``vitals_conformance_registry``, next to its reasons.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pytest

from tests.architecture.conformance_offline_scan import (
    LOCAL_HOST_RE,
    URL_RE,
    ImportGraph,
    SpawnSite,
    remote_hosts,
    spawn_sites,
)
from tests.architecture.vitals_conformance_registry import (
    CONFORMANCE_ROOTS,
    NETWORK_CAPABLE_BINARIES,
    SUBPROCESS_WAIVER_CEILING,
    SUBPROCESS_WAIVERS,
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
#:
#: That judgement got MORE load-bearing when the sweep went transitive (#11706),
#: not less: 396 of the 673 swept files reach ``httpx`` through
#: ``hydraflow_gateway``/``gateway_mint_client`` without importing it
#: themselves. Transitivity widens what the sweep can SEE; it must not widen
#: what counts as a reach. If closing the hole turns those 396 red, the closure
#: is wrong — the carriers are not.
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

# ``_LOCAL_HOST_RE``/``_URL_RE`` (now in ``conformance_offline_scan``) are kept
# for the negative control below and for the spawn-argv rule, NOT as a
# repo-wide sweep.
#
# A URL-literal sweep was the second thing tried and it is also wrong: fixture
# data legitimately contains ``https://github.com/...`` and sample payloads
# name hosts the test never contacts. Both proxies (imports-an-HTTP-library,
# names-a-URL) push toward an allow-list to stay green, and an allow-list that
# grows until it is the rule is the fail-open shape this standard exists to
# prevent. What remains is the check with zero false positives: importing a
# client that can ONLY mean a remote service.
#
# The URL proxy does come back in #11706, in the one place it has no false
# positives: inside the argv of a spawn call. ``https://github.com/x`` in a
# fixture is data; the same string in ``["git", "clone", ...]`` is a fetch.
# Scope, not the pattern, was what made the repo-wide version wrong.

# There is deliberately no allow-list for the import rule. One was written — a
# single entry exempting THIS file, on the theory that verifying "nothing
# reaches the network" requires naming what that means. It does not: the names
# live in ``_REMOTE_CLIENTS`` as strings and in the negative control as source
# written to ``tmp_path``, never as an import, so the exemption was a no-op that
# exempted the one file whose job is the rule. A no-op exemption is worse than
# none, because the day this file did import a remote client the sweep would
# have stayed green. It is swept like everything else.
#
# The subprocess rule DOES carry one (``SUBPROCESS_WAIVERS``), and the
# difference is not hypocrisy. An import is a fact about the file; a spawn's
# argv can be a fact about a call the test never makes, because monkeypatching
# is invisible to a parser. So that rule needs an escape hatch — and it is
# registered, carries its reason, is keyed by ``(path, binary)`` rather than by
# a rotting line number, must still match a live spawn, and is capped by a
# ceiling that may only ever be lowered.


@lru_cache(maxsize=1)
def _graph() -> ImportGraph:
    """The first-party import graph, resolved the way the suite imports.

    ``src`` then the repo root — the two entries ``tests/conftest.py`` puts on
    ``sys.path``. Built once so every property below shares one parse cache.
    """
    return ImportGraph((_REPO / "src", _REPO))


@lru_cache(maxsize=1)
def _conformance_files() -> tuple[Path, ...]:
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
    return tuple(out)


@lru_cache(maxsize=1)
def _all_spawn_sites() -> tuple[SpawnSite, ...]:
    sites: list[SpawnSite] = []
    for path in _conformance_files():
        sites.extend(spawn_sites(path, str(path.relative_to(_REPO))))
    return tuple(sites)


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


def test_the_sweep_has_a_subject() -> None:
    """ "Swept 0 files" must fail loudly, not read as "found nothing wrong"."""
    swept = _conformance_files()
    assert len(swept) > 100, (
        f"the offline sweep collected {len(swept)} files. Both properties below "
        "iterate this list, so a resolver or glob that stopped matching turns "
        "them green without observing anything."
    )


def test_no_conformance_check_imports_a_remote_client() -> None:
    """The load-bearing property, and the honest limit of a static check.

    A conformance check must be answerable offline from a clean checkout. If it
    imports a client that can only mean a remote service, the rule it claims to
    enforce is one outage away from being unanswerable — and an assurance seat
    auditable only through somebody else's uptime is not an assurance seat.

    Since #11706 the reach is TRANSITIVE. The one-file version had live carriers
    and no live subject: no ``src`` module imports a remote client today, so a
    conformance check that reached one through a local module would have been
    invisible and green. ``_ANTHROPIC_MODEL_ID`` already accepts Bedrock ids —
    one ``boto3``-backed client in ``src`` and the hole is live overnight.

    This catches *dependence on a service*, not *use of HTTP*: see the comment
    on ``_REMOTE_CLIENTS`` for the two proxies that were tried and rejected.
    Statically this is as far as it goes honestly; proving the suite actually
    runs with no network is a CI-lane concern, recorded in the standard.
    """
    graph = _graph()
    offenders = [
        reach.describe(_REPO)
        for path in _conformance_files()
        if (reach := graph.find(path, _REMOTE_CLIENTS)) is not None
    ]

    assert not offenders, (
        "conformance checks must run offline (docs/standards/vitals_conformance/). "
        "These reach a network:\n  " + "\n  ".join(offenders)
    )


def test_the_closure_actually_leaves_the_file_it_starts_from() -> None:
    """The transitive sweep's own vacuity guard.

    ``ImportGraph`` resolves dotted names against ``src``/ the repo root. If that
    resolution silently stops matching — a layout change, a package that becomes
    a namespace package, a base path that moves — every import degrades to
    "third-party leaf", the walk never leaves the starting file, and the sweep
    above quietly becomes the one-file version #11706 was filed about. Nothing
    would redden. This is the thing that reddens.
    """
    graph = _graph()
    swept = _conformance_files()
    transitive_only = 0
    for path in swept:
        direct, _ = graph.edges(path)
        reached, _ = graph.reach(path)
        if reached - direct:
            transitive_only += 1

    assert transitive_only >= len(swept) // 4, (
        f"only {transitive_only} of {len(swept)} conformance files reach a "
        "package they do not import directly. The first-party resolver has "
        "stopped resolving, and the sweep is one-file again."
    )


def test_the_gateway_httpx_carriers_stay_green() -> None:
    """Transitivity widens what is SEEN, never what COUNTS as a reach.

    ``hydraflow_gateway``/``gateway_mint_client`` import ``httpx``, and hundreds
    of conformance files import them. That is the correct state: an in-process
    ``MockTransport`` is not a network, so ``httpx`` is out of
    ``_REMOTE_CLIENTS`` on purpose. The tempting bug when closing #11706's first
    hole is to "prove" the new closure works by watching those files go red —
    which would mean the closure had smuggled the rejected imports-HTTP proxy
    back in through the transitive door.
    """
    graph = _graph()
    carriers = [
        path
        for path in _conformance_files()
        if "httpx" in (graph.reach(path)[0] - graph.edges(path)[0])
    ]
    assert len(carriers) > 50, (
        "the httpx-via-gateway carriers are gone. Either the gateway stopped "
        "using httpx, or the resolver stopped resolving — check which before "
        "trusting the sweep."
    )
    assert "httpx" not in _REMOTE_CLIENTS, (
        "httpx was added to the remote-client set. That reddens the "
        f"{len(carriers)} offline MockTransport carriers above and re-opens the "
        "false-positive problem the set was written to avoid."
    )
    for path in carriers:
        assert graph.find(path, _REMOTE_CLIENTS) is None


def test_no_conformance_check_spawns_a_network_binary() -> None:
    """The second dimension: an argv is a reach an import sweep cannot see.

    ``subprocess.run(["curl", ...])`` imports nothing remote. Neither does
    ``["gh", "api", ...]``, ``["aws", "s3", ...]`` or ``["bash", "-c", "wget …"]``.
    #11706 filed this with 73 of 673 swept files carrying a spawn primitive and
    the import sweep blind to every one.

    Two rules, because one binary list cannot carry both jobs:

    - the argv names a binary whose ordinary job is remote I/O
      (``NETWORK_CAPABLE_BINARIES``, and see the registry for the exclusions);
    - the argv names a remote host, whatever the binary. This is the URL proxy
      rejected repo-wide, readmitted where it has no false positives — inside a
      spawn's argv a hostname is a destination, not fixture data. It is what
      keeps ``git`` honest without a 130-entry waiver list: ``git status`` and
      ``git clone /tmp/x`` are local, ``git clone https://github.com/x`` is not.
    """
    waived = {(waiver.path, waiver.binary) for waiver in SUBPROCESS_WAIVERS}
    offenders: list[str] = []
    for site in _all_spawn_sites():
        binaries = [
            binary
            for binary in site.binaries(NETWORK_CAPABLE_BINARIES)
            if (site.path, binary) not in waived
        ]
        hosts = list(site.hosts())
        if binaries or hosts:
            reason = " and ".join(
                part
                for part in (
                    f"binaries {binaries}" if binaries else "",
                    f"hosts {hosts}" if hosts else "",
                )
                if part
            )
            offenders.append(f"{site.path}:{site.line} {site.call}(...) — {reason}")

    assert not offenders, (
        "conformance checks must run offline (docs/standards/vitals_conformance/). "
        "These shell out to a network:\n  " + "\n  ".join(offenders)
    )


def test_the_spawn_scanner_still_sees_spawns() -> None:
    """Vacuity guard for the second dimension.

    The rule above passes when nothing reaches a network AND when the scanner
    has stopped recognising spawns at all — a renamed wrapper, an aliased
    import, a new spawn primitive. Those two states are indistinguishable from
    the assertion, so pin the subject: the conformance roots really do shell
    out, roughly 165 times.
    """
    sites = _all_spawn_sites()
    assert len(sites) > 50, (
        f"the spawn scanner found {len(sites)} call sites in the conformance "
        "roots. It found ~165 when it was written; a count this low means it "
        "stopped recognising the primitives, not that the repo stopped spawning."
    )


def test_the_subprocess_waiver_list_is_shrink_only() -> None:
    """An allow-list that may grow is the failure this standard is about."""
    assert len(SUBPROCESS_WAIVERS) <= SUBPROCESS_WAIVER_CEILING, (
        f"{len(SUBPROCESS_WAIVERS)} subprocess waivers against a ceiling of "
        f"{SUBPROCESS_WAIVER_CEILING}. The ceiling may only ever be lowered — "
        "if a new conformance check needs to spawn a network binary, the "
        "question is whether it is a conformance check."
    )
    keys = [(waiver.path, waiver.binary) for waiver in SUBPROCESS_WAIVERS]
    assert len(keys) == len(set(keys)), f"duplicate waivers: {keys}"
    for waiver in SUBPROCESS_WAIVERS:
        assert len(waiver.why) > 40, (
            f"{waiver.path}/{waiver.binary} has no real rationale. A waiver "
            "without one is an allow-list entry with extra steps."
        )


def test_every_subprocess_waiver_is_still_live() -> None:
    """A dead waiver covers whatever lands in that file next.

    Same failure as a rotted line-window anchor (#11670): the exemption outlives
    the thing it excused and silently pre-approves its successor.
    """
    live = {
        (site.path, binary)
        for site in _all_spawn_sites()
        for binary in site.binaries(NETWORK_CAPABLE_BINARIES)
    }
    dead = [
        f"{waiver.path} no longer spawns {waiver.binary!r}"
        for waiver in SUBPROCESS_WAIVERS
        if (waiver.path, waiver.binary) not in live
    ]
    assert not dead, (
        "delete these waivers — they excuse nothing that still exists:\n  "
        + "\n  ".join(dead)
    )


def test_the_network_binary_list_is_not_empty() -> None:
    """The policy set the rule reads. Emptied, the rule passes on everything."""
    for binary in ("curl", "wget", "gh", "aws"):
        assert binary in NETWORK_CAPABLE_BINARIES, (
            f"{binary!r} left the network-binary list. Removing an entry is the "
            "loosening move; it needs the scrutiny a new waiver gets."
        )


# --------------------------------------------------------------------------
# Negative controls. Every property above passes on today's tree, so each one
# needs a mutation that proves it CAN fail — otherwise "it passes" is a claim
# about nothing, which is the exact shape this standard exists to stop.
# --------------------------------------------------------------------------


def _write(root: Path, spec: dict[str, str]) -> None:
    for rel, body in spec.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)


def test_the_remote_client_detector_actually_fires(tmp_path: Path) -> None:
    """Negative control for the direct reach. The sweep passes today, so prove
    it can fail.

    Without this, deleting the detector's body leaves a green test that has
    never observed a violation — the shape this whole standard exists to stop.
    """
    _write(
        tmp_path,
        {
            "test_victim.py": "import boto3\n\n\ndef test_x():\n    assert boto3\n",
            "test_nested.py": "def test_x():\n    import swamp\n\n    assert swamp\n",
        },
    )
    graph = ImportGraph((tmp_path,))

    direct = graph.find(tmp_path / "test_victim.py", _REMOTE_CLIENTS)
    assert direct is not None and direct.names == ("boto3",)

    nested = graph.find(tmp_path / "test_nested.py", _REMOTE_CLIENTS)
    assert nested is not None and nested.names == ("swamp",), (
        "a deferred import inside a function still reaches the service"
    )

    remote = tmp_path / "test_remote.py"
    remote.write_text('URL = "https://vitals.example.com/api"\n')
    assert remote_hosts(remote.read_text()) == ["vitals.example.com"]

    # The three shapes that must NOT fire: an in-process mock transport, a
    # loopback address, and an RFC-2606 sentinel host.
    clean = tmp_path / "test_clean.py"
    clean.write_text(
        "import httpx\n"
        'A = "https://zai.test/v1"\n'
        'B = "http://127.0.0.1:8000/health"\n'
        'C = "https://upstream.invalid/x"\n'
    )
    assert graph.find(clean, _REMOTE_CLIENTS) is None
    assert remote_hosts(clean.read_text()) == []
    assert URL_RE.search("https://vitals.example.com/api") is not None
    assert LOCAL_HOST_RE.search("zai.test") is not None


def test_a_transitive_reach_is_caught(tmp_path: Path) -> None:
    """Negative control for #11706's first hole.

    ``check`` imports ``bedrock``; ``bedrock`` imports ``boto3``. The pre-#11706
    sweep parsed ``check`` alone, saw ``{"bedrock"}``, intersected it with the
    remote clients, found nothing, and passed. This is the mutation that has to
    redden, and the depth is deliberate: two hops, an ``__init__`` re-export and
    a relative import, because ``src`` packages are shaped exactly like that.
    """
    _write(
        tmp_path,
        {
            "test_check.py": "from vendor import Client\n\n\ndef test_x():\n    assert Client\n",
            "vendor/__init__.py": "from .client import Client\n\n__all__ = ['Client']\n",
            "vendor/client.py": "import boto3\n\n\nclass Client:\n    session = boto3\n",
        },
    )
    graph = ImportGraph((tmp_path,))

    reach = graph.find(tmp_path / "test_check.py", _REMOTE_CLIENTS)
    assert reach is not None, (
        "a conformance check that reaches boto3 through two local hops was not "
        "caught — the closure is back to a one-file parse"
    )
    assert reach.names == ("boto3",)
    assert [p.name for p in reach.chain] == [
        "test_check.py",
        "__init__.py",
        "client.py",
    ]
    assert "vendor/client.py" in reach.describe(tmp_path)

    # And the shape that must NOT fire: the same two hops ending at httpx.
    _write(
        tmp_path,
        {
            "test_gateway.py": "from gw import mint\n\n\ndef test_x():\n    assert mint\n",
            "gw/__init__.py": "from .mint import mint\n\n__all__ = ['mint']\n",
            "gw/mint.py": "import httpx\n\n\ndef mint():\n    return httpx.MockTransport\n",
        },
    )
    assert graph.find(tmp_path / "test_gateway.py", _REMOTE_CLIENTS) is None, (
        "the gateway carriers must stay green: httpx through N hops is still "
        "not a network"
    )


def test_an_import_cycle_does_not_hang_the_closure(tmp_path: Path) -> None:
    """Cycles are real in ``src``; a naive walk would recurse forever."""
    _write(
        tmp_path,
        {
            "test_cycle.py": "import a\n\n\ndef test_x():\n    assert a\n",
            "a.py": "import b\n",
            "b.py": "import a\nimport requests\n",
        },
    )
    graph = ImportGraph((tmp_path,))
    reach = graph.find(tmp_path / "test_cycle.py", _REMOTE_CLIENTS)
    assert reach is not None and reach.names == ("requests",)


def test_the_spawn_detector_actually_fires(tmp_path: Path) -> None:
    """Negative control for #11706's second hole.

    Every one of these imports nothing in ``_REMOTE_CLIENTS``, so the import
    sweep — transitive or not — passes on all of them.
    """
    cases = {
        "test_curl.py": 'import subprocess\nsubprocess.run(["curl", "-fsS", "https://vitals.example.com/m"])\n',
        "test_gh.py": 'import subprocess\nsubprocess.check_output(["gh", "api", "rate_limit"])\n',
        "test_shell.py": 'import os\nos.system("set -e; wget -q https://pkgs.example.com/x")\n',
        "test_alias.py": 'import subprocess as sp\nsp.Popen(["aws", "s3", "ls"])\n',
        "test_bare.py": 'from subprocess import check_call\ncheck_call(["pip", "install", "x"])\n',
        "test_async.py": 'import asyncio\nasyncio.create_subprocess_exec("gh", "pr", "view")\n',
        "test_wrapper.py": 'async def f(): await run_subprocess("gh", "pr", "view")\n',
        "test_python_m.py": 'import subprocess\nsubprocess.run(["python", "-m", "pip", "install", "x"])\n',
        "test_git_clone.py": 'import subprocess\nsubprocess.run(["git", "clone", "https://github.com/o/r"])\n',
        "test_git_scp.py": 'import subprocess\nsubprocess.run(["git", "fetch", "git@github.com:o/r.git"])\n',
    }
    _write(tmp_path, cases)
    for rel in cases:
        sites = spawn_sites(tmp_path / rel, rel)
        assert sites, f"{rel}: no spawn site recognised at all"
        flagged = [
            site
            for site in sites
            if site.binaries(NETWORK_CAPABLE_BINARIES) or site.hosts()
        ]
        assert flagged, f"{rel}: spawn seen but not flagged as a network reach"


def test_the_spawn_detector_leaves_offline_spawns_alone(tmp_path: Path) -> None:
    """The false positives that would force the waiver list to grow.

    ``git`` against a ``tmp_path`` repo is 129 of the ~165 spawn sites in the
    conformance roots. If any of these fire, the fix is the detector, not a
    waiver.
    """
    cases = {
        "test_git_local.py": (
            "import subprocess\n"
            'subprocess.run(["git", "-C", "/tmp/r", "status", "--porcelain"])\n'
            'subprocess.run(["git", "clone", "/tmp/origin", "/tmp/clone"])\n'
            'subprocess.run(["git", "push", "origin", "main"])\n'
            'subprocess.run(["git", "commit", "-m", "feat: add a thing"])\n'
        ),
        "test_local_host.py": (
            "import subprocess\n"
            'subprocess.run(["true", "http://127.0.0.1:8000/health"])\n'
            'subprocess.run(["true", "https://zai.test/v1"])\n'
        ),
        # Spawn source as DATA — several conformance checks feed exactly this
        # to a scanner fixture. A text-level grep would flag every one.
        "test_fixture_source.py": (
            "SOURCE = '''\n"
            'async def f():\n    await asyncio.create_subprocess_exec("gh", "pr", "view")\n'
            "'''\n"
        ),
        "test_make.py": 'import subprocess\nsubprocess.run(["make", "quality"])\n',
    }
    _write(tmp_path, cases)
    for rel in cases:
        for site in spawn_sites(tmp_path / rel, rel):
            assert not site.binaries(NETWORK_CAPABLE_BINARIES), (
                f"{rel}:{site.line} false positive on {site.argv}"
            )
            assert not site.hosts(), f"{rel}:{site.line} false host on {site.argv}"


def test_a_waiver_covers_only_its_own_file_and_binary(tmp_path: Path) -> None:
    """The waiver key is ``(path, binary)``. Prove it does not over-cover.

    A waiver written as "this file is fine" would excuse the next network
    binary someone adds to it, which is how an exemption outlives its reason.
    """
    rel = "test_waived.py"
    _write(
        tmp_path,
        {
            rel: 'import subprocess\nsubprocess.run(["gh", "api", "x"])\nsubprocess.run(["curl", "x"])\n'
        },
    )
    waived = {(rel, "gh")}
    leftover = [
        binary
        for site in spawn_sites(tmp_path / rel, rel)
        for binary in site.binaries(NETWORK_CAPABLE_BINARIES)
        if (rel, binary) not in waived
    ]
    assert leftover == ["curl"]


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
    assert "transitive" in text.lower(), (
        "the standard still describes the one-file sweep #11706 replaced"
    )
    assert "subprocess" in text.lower(), (
        "the standard does not mention the spawn dimension it now enforces"
    )
