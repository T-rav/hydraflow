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
    "EGRESS_LANE_EXCLUSIONS",
    "EGRESS_LANE_EXCLUSION_CEILING",
    "EgressLaneExclusion",
    "ReachDetector",
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


#: EMPTY since #11706's egress lane landed, and the reason is the whole point
#: of building the lane rather than more parser.
#:
#: It held three entries, and all three said the same thing: *this call is
#: faked*. One monkeypatched ``asyncio.create_subprocess_exec``; two passed
#: ``cmd=["claude", ...]`` into an inversion-of-control seam with a recording
#: double in ``StreamConfig(runner=)``. A parser reads the call, never what the
#: call resolves to at runtime, so a hand-written waiver was the only honest
#: way to say it.
#:
#: ``test_no_conformance_check_spawns_a_network_binary`` no longer asks for one.
#: A statically flagged site is now ESCALATED: the file is run in a child
#: process with :mod:`tests.architecture.egress_guard` armed, and the question
#: "does this argv ever become a process?" is answered by watching the
#: interpreter's own ``subprocess.Popen``/``os.exec`` audit events. Measured on
#: those three files: 14 tests, 5 real spawns, all of them ``bash`` and
#: ``true`` — no ``gh``, no ``claude``, nothing to waive.
#:
#: The escalation is bounded BY the exception count, which is the property that
#: makes it affordable: only flagged sites are run, so a rule nobody trips
#: costs nothing and a rule tripped fifty times costs fifty test files. That is
#: the right pressure gradient for an exception mechanism to have.
SUBPROCESS_WAIVERS: tuple[SubprocessWaiver, ...] = ()

#: The waiver count. #11706 lowered it 3 -> 0 when the lane retired all three.
#:
#: This number may only ever be LOWERED. Raising it is precisely how an
#: allow-list grows until it *is* the rule, which is the fail-open shape the
#: whole standard exists to stop. At zero the statement is stronger than it
#: was: there is no hand-written exception to the spawn rule at all, and the
#: answer for a flagged site is to let the lane observe it.
SUBPROCESS_WAIVER_CEILING: int = 0


class ReachDetector(StrEnum):
    """How ``check_egress_exclusions.py`` proves an exclusion is still needed.

    Two, because the lane has two instruments and they see different things.
    Registering which one found a reach is not bookkeeping: pointing the wrong
    instrument at an entry answers "no reach observed" and reports a live
    exclusion as stale, which is the liveness check lying in the direction that
    reopens a hole.
    """

    HOOK = "hook"
    """The audit hook observes the reach in-process: a ``socket.connect`` or a
    spawn whose argv names a network binary or a host. Verified by running the
    file under the guard in observe mode and requiring at least one violation."""

    NAMESPACE = "namespace"
    """The reach happens inside a CHILD process, where no audit hook of ours
    runs — the kernel is the only witness. Verified the only way it can be:
    the file must FAIL when egress is blocked. A pass means the reach is gone
    and the exclusion with it."""


@dataclass(frozen=True, slots=True)
class EgressLaneExclusion:
    """One conformance file the egress-blocked lane does NOT run.

    Not a waiver. A waiver says "the static reading is wrong here"; this says
    "the lane's reading is RIGHT here, and the file reaches the network today".
    Each entry is a measured defect kept visible rather than a judgement kept
    quiet, and ``scripts/check_egress_exclusions.py`` reddens when one stops
    reaching — because an exclusion that outlives its reason pre-approves
    whatever lands in that file next (#11670's lesson, one mechanism over).
    """

    path: str
    """Repo-relative."""

    reaches: tuple[str, ...]
    """What was OBSERVED, not what was assumed. These come from a guarded run,
    not from reading the source — the source of every one of them is a helper
    the test calls, which is why the static scanner sees nothing."""

    detected_by: ReachDetector
    """Which instrument saw it, and therefore which one can re-check it."""

    why: str


#: The conformance files the lane skips, because they really do leave the
#: checkout. Found BY the lane on the day it was built (#11706): three files out
#: of the 691 the conformance roots contain, none of them visible to the static
#: scanner, because in every case a first-party helper does the spawning — the
#: residual the standard names and no amount of further AST work reaches.
#:
#: These are defects, and the list is shrink-only for that reason. The fix in
#: each case is to fake the seam the test already depends on; when someone does,
#: ``check_egress_exclusions.py`` reddens and says to delete the entry.
EGRESS_LANE_EXCLUSIONS: tuple[EgressLaneExclusion, ...] = (
    EgressLaneExclusion(
        path="tests/regressions/test_issue_10015_streak_escalation_autoclose.py",
        reaches=("gh api repos//compare/main...staging",),
        detected_by=ReachDetector.HOOK,
        why=(
            "StagingPromotionLoop's ahead-by probe runs unfaked: the loop reaches "
            "PRManager, which shells `gh api` against the real forge. Note the "
            "empty repo slug in the argv — the test is not even asking a "
            "meaningful question of the network, it just fails to stop the call."
        ),
    ),
    EgressLaneExclusion(
        path="tests/regressions/test_issue_8650.py",
        reaches=("gh issue list --repo hydra/hydraflow",),
        detected_by=ReachDetector.HOOK,
        why=(
            "the trust loop's staleness search runs against the real forge. The "
            "test asserts on escalation behaviour, so the live query's result is "
            "never read — it is latency and a rate-limit token, spent for nothing."
        ),
    ),
    EgressLaneExclusion(
        path="tests/regressions/test_issue_10253_airgap_start_orchestrator.py",
        reaches=(
            "gh run list --branch main --workflow ci.yml",
            "gh issue list --repo test-org/test-repo",
            "https://raw.githubusercontent.com (PricingRefreshLoop)",
        ),
        detected_by=ReachDetector.HOOK,
        why=(
            "the sharpest one, and the reason a lane beats a parser: the test is "
            "named test_wired_start_orchestrator_is_airgapped_and_stays_responsive "
            "and it is not air-gapped. Its own assertions pass — it exits 0 with "
            "all three reaches recorded — because the reaches happen in loops it "
            "starts and does not assert about. A gate reading the source finds "
            "nothing here; a gate watching the process finds three."
        ),
    ),
    EgressLaneExclusion(
        path="tests/architecture/test_mkdocs_strict.py",
        reaches=(
            "GET https://unpkg.com/mermaid@10.6.1/dist/mermaid.esm.min.mjs "
            "(mkdocs-mermaid2 url_exists check, every build)",
        ),
        detected_by=ReachDetector.NAMESPACE,
        why=(
            "the standard's own worked example of an orchestrator whose CONFIG "
            "reaches out — and its text said this build 'fetches nothing at "
            "build', which the lane disproved on its first run. mermaid2's "
            "`javascript` property calls `url_exists()`, which is a live "
            "`requests.get` of the CDN bundle on every `mkdocs build`; with no "
            "route out it warns and `--strict` aborts. Nothing in this repo "
            "could have found that statically: the reach is `requests` inside a "
            "plugin inside a child process, selected by two lines of "
            "`mkdocs.yml`. Fixing it means vendoring the mermaid bundle and "
            "changing what the published site loads, which is a docs decision "
            "and not this issue's."
        ),
    ),
)

#: The exclusion count on the day the lane landed (#11706). SHRINK-ONLY, for
#: the same reason the waiver ceiling is: a list of "files allowed to reach the
#: network" that may grow is the rule inverted.
#:
#: It is 4 and not 3 because the first measurement used the weaker of the lane's
#: two instruments. The audit hook found three reaches; the fourth happens
#: inside the ``mkdocs`` child process, where no hook of ours runs, and only
#: the network namespace saw it. Setting the number from the complete
#: measurement is not raising a ratchet — the constant had not landed yet — but
#: it is worth recording WHY it moved before it froze, because "our instrument
#: could not see it" is exactly the sentence this whole standard exists to make
#: someone say out loud.
EGRESS_LANE_EXCLUSION_CEILING: int = 4


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
