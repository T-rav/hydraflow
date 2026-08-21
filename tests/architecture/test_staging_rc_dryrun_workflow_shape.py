"""Shape guards for the staging RC dry-run sensor's checkout trust chain (#11518).

Code-scanning alert #108 (``actions/cache-poisoning/poisonable-step``) fired
because ``dryrun-shard`` checked out ``ref: ${{ needs.resolve.outputs.sha }}`` —
a job-output expression CodeQL must treat as untrusted — ahead of its privileged
build/test steps. The SHA was in fact safe (``resolve`` derives it via
``git rev-parse HEAD`` on the literal protected ``staging`` ref), but the shape
was indistinguishable from a genuinely poisonable one, so the alert could never
close. These tests pin the fixed shape so it cannot silently regress:

* the shard checks out the LITERAL protected ref and re-asserts the pin at run
  time (``pin`` step), skipping the tick with a ``::notice`` when staging
  advanced between ``resolve`` and the shard — never going red;
* a skipped tick still uploads one (skip-marker) summary per shard, because the
  reporter's ``download-artifact`` hard-fails on zero pattern matches and a
  skipped tick must stay green end-to-end;
* every checkout whose ref is an expression carries a ``# TRUST:`` comment
  block documenting why that expression is trusted — enforced fleet-wide for
  workflows triggered only by cadence (``schedule``/``workflow_dispatch``),
  which always run in default-branch context, CodeQL's actual cache-poisoning
  precondition. PR/push-triggered workflows run outside that context (and
  ``claude-security-review.yml`` deliberately checks out PR heads as an
  unprivileged advisory reviewer), so they are out of this pin's scope.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOWS = _REPO_ROOT / ".github" / "workflows"
_WORKFLOW = _WORKFLOWS / "staging-rc-dryrun.yml"

# Workflows whose triggers are a subset of these always run against the default
# branch with default-branch privileges (never PR-scoped) — the context in
# which a poisoned cache is actually readable by privileged runs.
_CADENCE_TRIGGERS = {"schedule", "workflow_dispatch"}

_JOB_KEY = re.compile(r"^  [A-Za-z0-9_-]+:\s*$")


def _load() -> dict:
    return yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))


def _raw_lines() -> list[str]:
    return _WORKFLOW.read_text(encoding="utf-8").splitlines()


def _job(wf: dict, job_id: str) -> dict:
    jobs = wf["jobs"]
    assert job_id in jobs, f"job {job_id!r} must exist"
    return jobs[job_id]


def _step_by_id(job: dict, step_id: str) -> dict:
    steps = [s for s in job["steps"] if s.get("id") == step_id]
    assert len(steps) == 1, f"exactly one step with id {step_id!r} required"
    return steps[0]


def _checkout_steps(job: dict) -> list[dict]:
    return [s for s in job["steps"] if "checkout" in str(s.get("uses", ""))]


def _job_line_slice(lines: list[str], job_id: str) -> tuple[int, int]:
    """Raw-text line range [start, end) of one top-level job block."""
    start = next(
        (i for i, ln in enumerate(lines) if ln.rstrip() == f"  {job_id}:"), None
    )
    assert start is not None, f"job {job_id!r} not found in raw workflow text"
    end = next(
        (i for i in range(start + 1, len(lines)) if _JOB_KEY.match(lines[i])),
        len(lines),
    )
    return start, end


def _comment_block_above(lines: list[str], idx: int) -> list[str]:
    """Contiguous comment lines directly above lines[idx] (blank = boundary)."""
    block: list[str] = []
    j = idx - 1
    while j >= 0 and lines[j].lstrip().startswith("#"):
        block.append(lines[j])
        j -= 1
    return list(reversed(block))


def _trust_flags_for_checkouts(lines: list[str], job_id: str) -> list[bool]:
    """One flag per checkout step (source order): carries a ``TRUST:`` block?"""
    start, end = _job_line_slice(lines, job_id)
    return [
        any("TRUST:" in c for c in _comment_block_above(lines, i))
        for i in range(start, end)
        if "uses: actions/checkout@" in lines[i]
    ]


def _triggers(doc: dict) -> set[str]:
    on = doc.get("on") or doc.get(True) or {}
    # `on` parses to the truthy key True under yaml.safe_load, so read both.
    return set(on.keys()) if isinstance(on, dict) else set(on)


def test_shard_checks_out_literal_staging_ref_not_a_job_output_expression() -> None:
    # Alert #108's taint source: the shard checked out an expression ref
    # (needs.resolve.outputs.sha) ahead of privileged build/test steps. The fix
    # checks out the literal protected default branch instead; the pin step
    # below restores the "one SHA per report" property at run time.
    checkouts = _checkout_steps(_job(_load(), "dryrun-shard"))
    assert len(checkouts) == 1, "the shard checks out exactly once"
    ref = str(checkouts[0].get("with", {}).get("ref", ""))
    assert ref == "staging", "shard must check out the literal protected ref"
    assert "${{" not in ref, "no job-output expression may name the checkout ref"


def test_shard_checkout_documents_the_trust_chain() -> None:
    # CodeQL cannot see that the resolved SHA is rev-parse of protected
    # staging; the comment block is the durable justification for the next
    # reader (and the marker the fleet-wide sweep looks for).
    flags = _trust_flags_for_checkouts(_raw_lines(), "dryrun-shard")
    assert flags == [True], "the shard checkout carries a TRUST: comment block"
    start, end = _job_line_slice(_raw_lines(), "dryrun-shard")
    block: list[str] = []
    for i in range(start, end):
        if "uses: actions/checkout@" in _raw_lines()[i]:
            block = _comment_block_above(_raw_lines(), i)
            break
    text = "\n".join(block)
    assert any(c.lstrip().startswith("# TRUST:") for c in block), (
        "the trust block starts with the literal `# TRUST:` marker"
    )
    assert "rev-parse" in text, "documents how resolve derives the SHA"
    assert "staging" in text, "names the protected ref the SHA comes from"


def test_pin_step_asserts_shard_head_equals_resolved_sha() -> None:
    # The pin step is what keeps "one SHA per report" without an
    # expression-ref checkout: compare this runner's literal-staging HEAD to
    # the SHA resolve captured, and on mismatch skip the tick (exit 0 +
    # ::notice; the next cadence tick re-runs) rather than go red.
    job = _job(_load(), "dryrun-shard")
    pin = _step_by_id(job, "pin")
    run = str(pin.get("run", ""))
    assert "git rev-parse HEAD" in run, "reads the checked-out HEAD"
    assert "needs.resolve.outputs.sha" in run, "compares against resolve's SHA"
    assert "matched=true" in run and "matched=false" in run
    assert "$GITHUB_OUTPUT" in run, "exports the matched flag for step gating"
    assert "::notice" in run, "mismatch is announced, not silently skipped"
    assert "::error" not in run and "exit 1" not in run, (
        "a staging advance between jobs is a skip, never a red tick"
    )
    steps = job["steps"]
    checkout_idx = next(
        i for i, s in enumerate(steps) if "checkout" in str(s.get("uses", ""))
    )
    assert steps.index(pin) == checkout_idx + 1, (
        "the pin runs directly after checkout, before anything privileged"
    )


def test_substantive_shard_steps_are_gated_on_the_pin() -> None:
    # On a mismatched tick the shard must not build or run anything against a
    # staging tip the report will not name — every substantive step after the
    # pin is gated on steps.pin.outputs.matched == 'true'.
    job = _job(_load(), "dryrun-shard")
    pin = _step_by_id(job, "pin")
    gated = job["steps"][job["steps"].index(pin) + 1 :]
    assert gated, "there are steps after the pin to gate"
    for step in gated:
        if "upload-artifact" in str(step.get("uses", "")):
            continue  # uploads are pinned separately (skip-marker contract)
        label = str(step.get("name") or step.get("uses") or step.get("run"))
        assert "steps.pin.outputs.matched == 'true'" in str(step.get("if", "")), (
            f"step {label!r} must be gated on the pin"
        )


def test_skipped_tick_still_uploads_one_summary_per_shard() -> None:
    # report's download-artifact@v4 hard-fails when its pattern matches zero
    # artifacts, and report keeps `if: always()`. A pin-mismatch tick therefore
    # writes a skip-marker summary (zero failures to the aggregator) and the
    # summary upload keeps its unconditional `if: always()` — skipped ticks
    # stay green end-to-end and file no spurious issue.
    pin = _step_by_id(_job(_load(), "dryrun-shard"), "pin")
    run = str(pin.get("run", ""))
    assert "/tmp/summary.json" in run, "mismatch writes the summary path"
    assert '"failed": []' in run, "skip marker contributes zero failures"
    assert '"skipped"' in run, "skip marker says why it skipped"
    uploads = [
        s
        for s in _job(_load(), "dryrun-shard")["steps"]
        if "upload-artifact" in str(s.get("uses", ""))
    ]
    summary = [
        s for s in uploads if "summary" in str(s.get("with", {}).get("name", ""))
    ]
    assert len(summary) == 1, "exactly one summary upload step"
    assert str(summary[0].get("if")) == "always()", (
        "the summary upload runs on every outcome, matched or skipped"
    )


def test_report_pins_to_the_tested_sha_with_documented_trust() -> None:
    # report MUST keep the expression ref: it runs the reporter script from the
    # exact commit the shards tested, not a possibly-advanced staging tip
    # (literal staging here would analyze a commit nobody tested). The
    # expression is safe — resolve derives it from protected staging — so it
    # ships with the documented TRUST marker instead of a refactor.
    job = _job(_load(), "report")
    checkouts = _checkout_steps(job)
    assert len(checkouts) == 1, "report checks out exactly once"
    ref = str(checkouts[0].get("with", {}).get("ref", ""))
    assert ref == "${{ needs.resolve.outputs.sha }}", (
        "report stays pinned to the resolved (tested) SHA"
    )
    flags = _trust_flags_for_checkouts(_raw_lines(), "report")
    assert flags == [True], "report's expression checkout carries TRUST: docs"


def test_cadence_only_workflows_expression_refs_carry_trust_markers() -> None:
    # Fleet-wide regression pin: in workflows that run ONLY on cadence triggers
    # (always default-branch context — where a poisoned cache is readable by
    # privileged runs), a checkout ref may be a literal/absent ref, or an
    # expression justified by a TRUST: comment block. Anything else re-opens
    # the alert-#108 shape.
    offenders: list[str] = []
    for wf_path in sorted(_WORKFLOWS.glob("*.yml")):
        doc: dict[str, Any] = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
        if not _triggers(doc) <= _CADENCE_TRIGGERS:
            continue
        lines = wf_path.read_text(encoding="utf-8").splitlines()
        for job_id, job in (doc.get("jobs") or {}).items():
            checkouts = _checkout_steps(job)
            flags = _trust_flags_for_checkouts(lines, str(job_id))
            assert len(flags) == len(checkouts), (
                f"{wf_path.name}:{job_id} raw checkout lines must match YAML steps"
            )
            for step, trusted in zip(checkouts, flags, strict=True):
                ref = str(step.get("with", {}).get("ref", ""))
                if "${{" in ref and not trusted:
                    offenders.append(f"{wf_path.name}:{job_id} ref={ref!r}")
    assert not offenders, (
        "expression-ref checkouts in cadence-only workflows need a documented "
        f"# TRUST: justification (or a literal protected ref): {offenders}"
    )
