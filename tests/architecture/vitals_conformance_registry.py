"""Which claims are vitals (externalisable) and which are conformance (not).

The rule is in ``docs/standards/vitals_conformance/README.md``:

    If the claim is *what the number is*, it is vitals and may live in an
    external data plane. If the claim is *that a rule holds*, it is conformance
    and must be answerable offline from a clean checkout.

Registration is manual and explicit, for the same reason
``path_membership_registry`` is: discovery-by-convention would be the failure
mode one level up — a rule that quietly stops seeing its subject. A check
nobody registers is a check nobody classified.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

__all__ = [
    "CONFORMANCE_ROOTS",
    "NETWORK_CAPABLE_BINARIES",
    "SUBPROCESS_WAIVER_CEILING",
    "SUBPROCESS_WAIVERS",
    "Claim",
    "ClaimKind",
    "SubprocessWaiver",
    "registered_claims",
    "repo_root",
]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


class ClaimKind(StrEnum):
    VITALS = "vitals"
    """A measurement. May be emitted to an external plane."""

    CONFORMANCE = "conformance"
    """An assertion that a rule holds. Must be answerable offline."""


@dataclass(frozen=True, slots=True)
class Claim:
    """One registered artifact or gate, and what kind of claim it makes."""

    name: str
    kind: ClaimKind
    path: str
    """Repo-relative. Must resolve — a claim about a file that is gone is not a
    claim, and that is the #11673 lesson applied here."""

    why: str
    """The answer to "what breaks if the external plane is down?"."""


#: Directories whose contents are conformance by construction. Anything under
#: them enforces a rule rather than reporting a number, so the offline
#: constraint applies to the whole tree rather than per-file.
CONFORMANCE_ROOTS: tuple[str, ...] = (
    "tests/architecture",
    "tests/regressions",
)


#: Binaries whose ORDINARY JOB is talking to something remote. A conformance
#: check that spawns one has left the checkout, and an import sweep cannot see
#: it: ``subprocess.run(["curl", ...])`` imports nothing (#11706).
#:
#: The line is drawn at *the binary's own purpose*, not at "could conceivably
#: reach a network", and three exclusions are deliberate:
#:
#: - ``git`` — 129 of the ~165 spawn sites in the conformance roots are ``git``,
#:   every one of them driving a throwaway repo under ``tmp_path``. Listing it
#:   would need a ~130-entry waiver list, which is the allow-list-that-becomes-
#:   the-rule shape this standard exists to prevent. Its network subcommands are
#:   caught by the second rule instead: ``git clone https://…`` and
#:   ``git@host:repo`` carry a remote host in the argv, and that reddens.
#: - ``make``/``pytest``/``mkdocs`` — orchestrators. They reach a network only
#:   through what they are configured to invoke, which is a property of
#:   ``Makefile``/``mkdocs.yml`` rather than of the argv. Static analysis cannot
#:   see it; the egress-blocked lane can. Recorded as residual in the standard.
#: - ``python``/``sys.executable`` — ``python -m pip`` is caught by ``pip``
#:   appearing as an argv token, which is the part that means the network.
#:
#: Adding a binary TIGHTENS the rule and needs no ceremony. Removing one is the
#: loosening move and deserves the scrutiny a new waiver gets.
NETWORK_CAPABLE_BINARIES: frozenset[str] = frozenset(
    {
        # Transfer and raw sockets.
        "curl",
        "wget",
        "nc",
        "ncat",
        "netcat",
        "telnet",
        "ftp",
        "sftp",
        "ssh",
        "scp",
        "rsync",
        # Forge and cloud control planes.
        "gh",
        "glab",
        "hub",
        "aws",
        "gcloud",
        "az",
        "kubectl",
        "helm",
        "terraform",
        "flyctl",
        "wrangler",
        "vercel",
        # Package managers — an index fetch is the default behaviour.
        "pip",
        "pip3",
        "pipx",
        "uv",
        "uvx",
        "poetry",
        "conda",
        "npm",
        "npx",
        "yarn",
        "pnpm",
        "bower",
        "cargo",
        "composer",
        "brew",
        "apt",
        "apt-get",
        "yum",
        "dnf",
        "apk",
        # Registries and model planes.
        "docker",
        "docker-compose",
        "podman",
        "skopeo",
        "ollama",
        "huggingface-cli",
        "claude",
        "codex",
    }
)


@dataclass(frozen=True, slots=True)
class SubprocessWaiver:
    """One conformance file permitted to name one network binary in an argv.

    Keyed by ``(path, binary)`` and NOT by line number, on purpose: every
    line-window anchor in this repo was already vacuous when someone finally
    looked (#11670), two of them pointing past end-of-file. A waiver anchored
    to a line rots into a waiver for whatever moved into that line.
    """

    path: str
    """Repo-relative."""

    binary: str
    why: str
    """Why the argv names it without the check leaving the checkout."""


#: The registered exceptions. An unregistered allow-list would be #11706 one
#: level up — a rule kept green by a set nobody classified.
SUBPROCESS_WAIVERS: tuple[SubprocessWaiver, ...] = (
    SubprocessWaiver(
        path="tests/regressions/test_reap_processlookuperror.py",
        binary="gh",
        why=(
            "argv is ['gh', 'issue', 'list'] but the test monkeypatches "
            "asyncio.create_subprocess_exec to return a dead-process double "
            "before calling run_simple, so nothing is ever spawned. The argv is "
            "documentary — it models the shape of the real call whose reap "
            "semantics (#9794/#9814) are under test. A static reader cannot see "
            "a monkeypatch; rewriting the argv to appease it would trade a "
            "faithful fixture for a green sweep."
        ),
    ),
)

#: The waiver count on the day the subprocess dimension landed (#11706).
#:
#: This number may only ever be LOWERED. Raising it is precisely how an
#: allow-list grows until it *is* the rule, which is the fail-open shape the
#: whole standard exists to stop — so a new exception is a conversation, not an
#: edit. A waiver that no longer matches a live spawn must be deleted, not left
#: to cover the next thing that lands in that file.
SUBPROCESS_WAIVER_CEILING: int = 1


def registered_claims() -> tuple[Claim, ...]:
    """Every classified artifact and gate."""
    return (
        # --- VITALS: counters. What the number is. ---------------------------
        Claim(
            name="erosion.mass",
            kind=ClaimKind.VITALS,
            path="disturbance/baselines/mass.yaml",
            why=(
                "god-class/file sizes. Losing the plane loses the trend, not the "
                "ratchet: test_mass_ratchet reads this file, not a service."
            ),
        ),
        Claim(
            name="erosion.suite_hygiene",
            kind=ClaimKind.VITALS,
            path="disturbance/baselines/suite_hygiene.yaml",
            why="parametrize copies and cross-file duplicates. A count.",
        ),
        Claim(
            name="erosion.suppressions",
            kind=ClaimKind.VITALS,
            path="disturbance/baselines/suppressions.yaml",
            why="how many suppressions exist. The shrink-only rule is the gate.",
        ),
        Claim(
            name="erosion.concentration",
            kind=ClaimKind.VITALS,
            path="disturbance/baselines/concentration.yaml",
            why="module fan-in counts.",
        ),
        Claim(
            name="erosion.traceability",
            kind=ClaimKind.VITALS,
            path="disturbance/baselines/traceability.yaml",
            why="untraced percentage. A fraction.",
        ),
        Claim(
            name="erosion.mock_spec",
            kind=ClaimKind.VITALS,
            path="disturbance/baselines/mock_spec.yaml",
            why="mock-spec violation count.",
        ),
        Claim(
            name="vitals.emitter",
            kind=ClaimKind.VITALS,
            path="scripts/emit_vitals.py",
            why=(
                "the thing that ships the counters. Carries no assertion that a "
                "gate holds, and a test in tests/test_emit_vitals.py enforces that."
            ),
        ),
        # --- CONFORMANCE: rules. That a rule holds. --------------------------
        Claim(
            name="ratchet.disturbance",
            kind=ClaimKind.CONFORMANCE,
            path="tests/test_disturbance_ratchet.py",
            why=(
                "shrink-only is a RULE over the counters above. The counts are "
                "vitals; 'it did not grow' is conformance and must hold offline."
            ),
        ),
        Claim(
            name="ratchet.mass",
            kind=ClaimKind.CONFORMANCE,
            path="tests/architecture/test_mass_ratchet.py",
            why="'no new god class beyond the baseline' is a rule, not a number.",
        ),
        Claim(
            name="ratchet.baseline_keys_resolve",
            kind=ClaimKind.CONFORMANCE,
            path="tests/architecture/test_ratchet_baseline_keys_resolve.py",
            why=(
                "'every baseline key still names a real file' — the guard that "
                "makes a re-keyed entry loud instead of reading as progress "
                "(#11680). Pure filesystem."
            ),
        ),
        Claim(
            name="path_membership.registry",
            kind=ClaimKind.CONFORMANCE,
            path="tests/architecture/path_membership_registry.py",
            why=(
                "'every path-membership entry resolves, and membership follows a "
                "module into a package' (#11673). Repo knowledge; unsamplable."
            ),
        ),
        Claim(
            name="offline_conformance.scan",
            kind=ClaimKind.CONFORMANCE,
            path="tests/architecture/conformance_offline_scan.py",
            why=(
                "'no conformance check reaches a remote client, transitively or "
                "by spawning one' (#11706). Pure AST over the checkout; the day "
                "it needs a service to answer, the rule it enforces is gone."
            ),
        ),
        Claim(
            name="adr.source_citations",
            kind=ClaimKind.CONFORMANCE,
            path="tests/architecture/test_adr_source_citations_exist.py",
            why="'every ADR citation resolves against the source tree'.",
        ),
        Claim(
            name="adr.enforcement_ratchet",
            kind=ClaimKind.CONFORMANCE,
            path="tests/architecture/test_adr_enforcement_ratchet.py",
            why="'accepted ADRs carry enforcement' is a rule about the ADRs.",
        ),
        Claim(
            name="credit_reraise.completeness",
            kind=ClaimKind.CONFORMANCE,
            path="tests/test_loop_credit_reraise_completeness.py",
            why=(
                "'no broad handler swallows a credit or likely-bug exception' — "
                "#6855's guard, which was absent for months while green (#11670)."
            ),
        ),
        Claim(
            name="mkdocs.strict",
            kind=ClaimKind.CONFORMANCE,
            path="tests/architecture/test_mkdocs_strict.py",
            why="'every cross-link resolves'. Builds the site locally.",
        ),
    )
