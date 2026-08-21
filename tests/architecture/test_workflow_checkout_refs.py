"""Guard: no ``actions/checkout`` step checks out a job-output ref (#11518, #11565).

CodeQL alert #108 (``actions/cache-poisoning/poisonable-step``) fired on
``staging-rc-dryrun.yml``: a job running with default-branch privilege
(``schedule`` / ``workflow_dispatch``) checked out
``ref: ${{ needs.resolve.outputs.sha }}`` and then ran cache-writing steps.
That SHA happened to be ``git rev-parse HEAD`` of protected ``staging`` — but a
job output is opaque to static analysis, and the *shape* is what gets flagged:
a privileged job executing whatever another job told it to execute. The same
shape existed, unflagged, in ``rc-promotion-scenario.yml`` — three jobs checked
out ``needs.gate.outputs.pr_ref``, a ``refs/pull/N/merge`` that the scheduled
path resolved by ``gh api`` from "the first open PR whose head is named
``rc/*``" (#11565). In a public repo that lookup matches a fork PR.

The sibling sweep in ``test_staging_rc_dryrun_workflow_shape.py`` is narrower:
it flags expression refs only in jobs that also write a cache, and accepts a
``# TRUST:`` marker as justification. This guard is the blunt instrument behind
it — *any* checkout whose ``ref:`` names ``needs.<job>.outputs.<key>`` fails,
fleet-wide, marker or not. The trust-correct shapes are:

* a literal protected ref (``ref: staging`` / ``ref: main``), plus an in-job
  assertion against the resolved SHA where one exact commit matters
  (``scripts/staging_rc_dryrun_pin.py``); or
* no ``ref:`` at all in a ``pull_request`` job — the event's own merge ref,
  with a PR-scoped cache and a PR-scoped token.

Moving the job output into a ``run:`` step (``git fetch origin "$REF"``) is
not a fix — it hides the shape from CodeQL without changing who controls the
code. Reviewers, not this guard, catch that; do not "fix" a red here that way.

``ALLOWED_JOB_OUTPUT_CHECKOUTS`` is the only way past this guard. It starts
EMPTY, every entry names its reason, and an entry that no longer matches an
offender fails too — the allowlist cannot outlive the exception it names.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

#: ``needs.<job>.outputs.<key>`` anywhere in the ref — inside ``${{ }}`` with or
#: without padding, embedded in a longer string such as
#: ``refs/pull/${{ needs.gate.outputs.pr_number }}/merge``, or wrapped in a
#: function call. Both property forms GitHub's expression grammar accepts are
#: covered: dot access (``needs.gate.outputs.pr_ref``) and single-quoted index
#: access (``needs['gate']['outputs']['pr_ref']``), mixed freely.
_PROPERTY = r"(?:\.(?:[A-Za-z0-9_-]+|\*)|\[\s*'[^']*'\s*\])"
_OUTPUTS = r"(?:\.outputs|\[\s*'outputs'\s*\])"
JOB_OUTPUT_REF_RE = re.compile(rf"\bneeds{_PROPERTY}{_OUTPUTS}{_PROPERTY}")

#: ``"<workflow file>:<job key>" -> reason``. Deliberately EMPTY. Adding an
#: entry is a reviewed decision that a privileged job may execute code named
#: by another job; the reason must say who controls that output and why the
#: job's cache cannot be poisoned through it.
ALLOWED_JOB_OUTPUT_CHECKOUTS: dict[str, str] = {}

#: The verbatim ref from alert #108, so the classifier is pinned to the real
#: finding and not only to synthetic examples.
ALERT_108_REF = "${{ needs.resolve.outputs.sha }}"


def _workflow_files() -> list[Path]:
    return sorted(
        path for pattern in ("*.yml", "*.yaml") for path in WORKFLOW_DIR.glob(pattern)
    )


def _load(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{path.name}: workflow did not parse to a mapping"
    return data


def _jobs(workflow: dict) -> dict[str, dict]:
    return {
        key: job
        for key, job in (workflow.get("jobs") or {}).items()
        if isinstance(job, dict)
    }


def _steps(job: dict) -> list[dict]:
    return [step for step in job.get("steps") or [] if isinstance(step, dict)]


def _is_checkout(step: dict) -> bool:
    return str(step.get("uses", "")).startswith("actions/checkout@")


def _checkout_ref(step: dict) -> str:
    return str((step.get("with") or {}).get("ref", ""))


def references_job_output(ref: str) -> bool:
    """True when ``ref`` names a ``needs.<job>.outputs.<key>`` value."""
    return JOB_OUTPUT_REF_RE.search(ref) is not None


def checkout_sites() -> list[tuple[str, str, str]]:
    """Every ``(workflow file, job key, ref)`` for every checkout step in the fleet."""
    sites: list[tuple[str, str, str]] = []
    for path in _workflow_files():
        for job_key, job in _jobs(_load(path)).items():
            sites.extend(
                (path.name, job_key, _checkout_ref(step))
                for step in _steps(job)
                if _is_checkout(step)
            )
    return sites


def offenders() -> dict[str, str]:
    """``"<file>:<job>" -> ref`` for every checkout of a job-output ref."""
    return {
        f"{workflow}:{job}": ref
        for workflow, job, ref in checkout_sites()
        if references_job_output(ref)
    }


class TestClassifier:
    @pytest.mark.parametrize(
        "ref",
        [
            ALERT_108_REF,
            "${{needs.gate.outputs.pr_ref}}",
            "refs/pull/${{ needs.gate.outputs.pr_number }}/merge",
            "${{ needs.resolve-sha.outputs.head_sha }}",
            # Index syntax is the same read through a different door.
            "${{ needs['gate']['outputs']['pr_ref'] }}",
            "${{ needs.gate['outputs'].pr_ref }}",
            "${{ needs[ 'resolve' ].outputs[ 'sha' ] }}",
            "${{ fromJSON(needs.resolve.outputs.meta).sha }}",
            "${{ needs.*.outputs.sha }}",
        ],
    )
    def test_job_output_refs_are_flagged(self, ref: str) -> None:
        assert references_job_output(ref)

    @pytest.mark.parametrize(
        "ref",
        [
            "",
            "staging",
            "main",
            "refs/heads/main",
            # Event/context values are a different trust question (CodeQL's
            # actions/untrusted-checkout family) and out of this guard's scope.
            "${{ github.event.pull_request.head.sha }}",
            "${{ github.sha }}",
            "${{ inputs.ref }}",
            # A job *result* is not a job output; only outputs carry text.
            "${{ needs.gate.result }}",
        ],
    )
    def test_literal_and_context_refs_are_not_flagged(self, ref: str) -> None:
        assert not references_job_output(ref)


class TestFleet:
    def test_every_workflow_parses(self) -> None:
        # A file the guard cannot read is a blind spot, not a pass.
        files = _workflow_files()
        assert files, "no workflows found under .github/workflows"
        for path in files:
            _load(path)

    def test_fleet_has_checkout_steps_to_inspect(self) -> None:
        # Sanity: the walker actually reaches steps, so a green result below
        # is not a vacuous pass from a broken traversal.
        sites = checkout_sites()
        assert len(sites) > 1, sites
        assert len({workflow for workflow, _, _ in sites}) > 1, sites

    def test_no_checkout_uses_a_job_output_ref(self) -> None:
        found = offenders()
        unexplained = {
            site: ref
            for site, ref in found.items()
            if site not in ALLOWED_JOB_OUTPUT_CHECKOUTS
        }
        assert not unexplained, (
            "actions/checkout of a job-output ref (the alert-#108 cache-poisoning "
            "shape). Check out the literal protected ref and assert the SHA "
            "in-job, or drop `ref:` in a pull_request job; see this module's "
            "docstring. Offenders:\n"
            + "\n".join(
                f"  {site}: ref: {ref}" for site, ref in sorted(unexplained.items())
            )
        )


class TestAllowlist:
    def test_allowlist_starts_empty_and_only_grows_by_reviewed_exception(self) -> None:
        # Ratchet: the day this has an entry, the reason must name the trust
        # chain — not "CodeQL false positive".
        for site, reason in ALLOWED_JOB_OUTPUT_CHECKOUTS.items():
            assert re.fullmatch(r"[A-Za-z0-9_.-]+\.ya?ml:[A-Za-z0-9_-]+", site), site
            assert len(reason.strip()) >= 40, f"{site}: reason too thin to review"

    def test_allowlist_entries_are_still_offenders(self) -> None:
        # An exemption must not outlive the exception it names.
        stale = set(ALLOWED_JOB_OUTPUT_CHECKOUTS) - set(offenders())
        assert not stale, f"allowlisted but no longer a job-output checkout: {stale}"
