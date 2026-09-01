"""Which checks may report ``NA`` — and the reviewed reason each one may.

``runner.overall_exit_code`` used to read "0 if every finding is PASS/NA". That
one line is what let P2.3, P2.4, P2.6 and P2.7 sit inert from the day they were
written while ``make audit`` reported green: all four shelled out to
``scripts/check_layer_imports.py``, which #8383 deleted less than four hours
after #8386 merged them. They returned ``NA`` — "layer-check pending", "domain
purity unverified" — for every repo, forever, and ``NA`` counted as success.

**An absent subject is not a passing subject.** So ``NA`` is no longer a status
a check can simply choose. It is a claim that has to be registered here, in
advance, with a reason a reviewer can check. :func:`runner._run_one` upgrades
any ``NA`` from a check that is not in this table to :attr:`Status.INERT`,
which fails the gate.

The default is therefore LOUD. A new check that hits an unforeseen "nothing to
measure" path does not quietly join the green column — it reddens, and whoever
adds it has to come here and write down why that state is legitimate. Silence
costs something, which is the only reason it stays honest.

Two rules for adding an entry:

1. **The reason must be about the CHECK, not about this repo.** Check ids come
   from ADR-0044, which every audited repo shares, so an entry is a statement
   that holds for HydraFlow, for a greenfield kernel, and for any managed repo
   alike. "HydraFlow has no ``src/ui``" is not a reason; "a repo with no ``ui/``
   tree has no browser surface to E2E-test" is.
2. **"The check could not run" is never an NA reason.** A timed-out ``git log``,
   an unresolvable base ref, a deleted helper script — those are ``INERT``, and
   the check must return ``Status.INERT`` at that site. Registering a check here
   blesses only its genuinely-not-applicable paths; it does not launder its
   broken ones, because those no longer come through as ``NA`` at all.
"""

from __future__ import annotations

#: Check ids permitted to report ``NA``, each mapped to why that is legitimate.
#:
#: Keys are ADR-0044 check ids. Anything absent from this table that returns
#: ``NA`` becomes ``INERT`` and fails the audit — see the module docstring.
NA_JUSTIFICATIONS: dict[str, str] = {
    # --- P1: docs -------------------------------------------------------
    "P1.8": (
        "background-loop documentation is only meaningful for orchestration-"
        "shaped repos; a library or service with no long-running loops has no "
        "such entry to write"
    ),
    "P1.14": (
        "the load-bearing ADR set (0001/0002/0003/...) describes orchestration "
        "topology; a non-orchestration repo is not expected to carry it"
    ),
    "P1.16": (
        "a repo with no docs/adr/ has no ADR corpus to scan for status rows; "
        "the missing directory itself is P1's subject, reported there"
    ),
    "P1.17": (
        "same as P1.16 — no docs/adr/ means no control-plane ADR whose lineage "
        "lines could be checked"
    ),
    # --- P2: architecture -----------------------------------------------
    "P2.7": (
        "domain purity is a claim about a domain layer; a repo that declares "
        "neither a models module nor a domain/ package has no such layer for "
        "the check to judge. NOTE: this is the ONLY NA path P2.7 has — it no "
        "longer shells out to a script that may be missing (#8383)"
    ),
    "P2.8": (
        "the anaemic-domain sample is deliberately restricted to non-DTO "
        "classes; a domain modelled entirely as Pydantic/TypedDict/frozen "
        "dataclass DTOs has nothing this check is allowed to judge, and "
        "ADR-0044 P2 explicitly exempts those shapes"
    ),
    "P2.9": (
        "the ToC-to-wiki term flow needs both CLAUDE.md and a docs/wiki/"
        "architecture*.md to compare; when either is missing that absence is "
        "already a P1 failure and double-reporting it here would blame the "
        "wrong principle"
    ),
    # --- P3: testing ----------------------------------------------------
    "P3.11": (
        "browser E2E is only required where there is a browser surface; a repo "
        "with no ui/ tree has none"
    ),
    "P3.14": (
        "the stateful-fake check judges Fake classes; a repo that declares no "
        "fake directories has none to judge, and their absence is P3's own "
        "upstream check"
    ),
    "P3.19": (
        "the optional-dependency import guard needs declared extras to guard; "
        "a pyproject with no optional-dependencies has no optional import to "
        "place behind a graceful-degradation path"
    ),
    # --- P5: CI ---------------------------------------------------------
    "P5.5": (
        "branch protection is read through the GitHub API, and the default CI "
        "GITHUB_TOKEN lacks the `administration` scope; an HTTP 403 is a token "
        "limit, not a governance violation, and failing on it would make every "
        "CI run red for a permission the audit is not meant to demand"
    ),
    "P5.6": (
        "the direct-push scan reads merged history; a non-git checkout (a "
        "tarball, an export) has no history to read, and a repo with no "
        "main/master ref has no trunk whose pushes could be judged"
    ),
    # --- P6: agents -----------------------------------------------------
    "P6.1": "P6 describes multi-agent orchestration; informational for other repo shapes",
    "P6.2": "P6 describes multi-agent orchestration; informational for other repo shapes",
    "P6.3": "P6 describes multi-agent orchestration; informational for other repo shapes",
    "P6.4": "P6 describes multi-agent orchestration; informational for other repo shapes",
    "P6.5": "P6 describes multi-agent orchestration; informational for other repo shapes",
    # --- P7: observability ----------------------------------------------
    "P7.3a": (
        "the three-layer wiki shape can only be judged where a repo_wiki/ "
        "exists; its absence is P7's own upstream check, reported there"
    ),
    "P7.4": "no source tree means nothing to scan for instrumentation",
    "P7.5": "no source tree means nothing to scan for instrumentation",
    # --- P9: persistence ------------------------------------------------
    "P9.8": "no source tree means no persistence code to scan",
    # --- P10: TDD -------------------------------------------------------
    "P10.2": ("no source tree means no modules whose test partners could be paired"),
    "P10.3": (
        "the fix-commit history scan needs a git checkout; a tarball export has "
        "no history. (A git command that FAILS is INERT, not NA — see the "
        "module docstring.)"
    ),
    "P10.4": (
        "the assertion-density sample needs tests/ and at least one test "
        "function; a repo with neither has nothing to sample, and the absent "
        "tests/ is already P3's subject"
    ),
    "P10.5": "same as P10.4 — no tests/ and no test functions means no sample",
    "P10.6": (
        "the per-PR regression-delta gate is scoped to PR CI by design: it "
        "diffs the PR against its merge base. Run outside a PR context "
        "(HYDRAFLOW_AUDIT_PR_BASE unset) there is no diff to judge, and the "
        "merged-history equivalent is P10.3/P10.7"
    ),
    "P10.8": (
        "the test-pyramid gate is scoped to PR CI by design: it judges the "
        "shape of the change under review against the standard's matrix, and "
        "reuses P10.6's merge-base diff. Run outside a PR context "
        "(HYDRAFLOW_AUDIT_PR_BASE unset) there is no change to judge. Without "
        "this entry the check reports NA and the audit correctly downgrades it "
        "to INERT — a check advertising work it did not do"
    ),
    "P10.7": (
        "the false-close detector reads merged history; a non-git checkout has "
        "none. (A git command that FAILS is INERT, not NA.)"
    ),
}
