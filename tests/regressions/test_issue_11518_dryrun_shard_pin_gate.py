"""Regression for #11518: an unverified SHA must skip every privileged step.

CodeQL alert #108 (``actions/cache-poisoning/poisonable-step``) was fixed by
swapping the ``dryrun-shard`` checkout from ``ref: ${{ needs.resolve.outputs.sha
}}`` to the literal protected branch. That trade is only safe because of the
``pin`` step: the branch tip can advance between ``resolve`` and the shard, and
running the suite on a different commit than the report names would silently
corrupt the sensor's "one SHA per report" property.

The shape test pins that the gates exist; the pin test executes the comparison.
Neither, alone, proves the pair actually *composes* — a correct script wired to
an inverted or misspelled ``if:`` still lets a cache-writing step run on an
unasserted commit. So this test joins them: it runs the **real**
``scripts/staging_rc_dryrun_pin.py``, takes the ``matched`` value it really
wrote to ``$GITHUB_OUTPUT``, and evaluates the **real** ``if:`` expressions
lifted from the workflow against it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from scripts.staging_rc_dryrun_pin import main as pin_main

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "staging-rc-dryrun.yml"

_RESOLVED_SHA = "c" * 40
_ADVANCED_SHA = "d" * 40

#: Every ``if:`` form this evaluator understands. A step using anything else
#: fails ``test_every_gate_expression_is_understood`` rather than being silently
#: mis-evaluated into a false pass.
_KNOWN_CONDITIONS = {
    "",
    "always()",
    "failure()",
    "steps.pin.outputs.matched == 'true'",
}


def _shard_steps() -> list[dict]:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return [s for s in workflow["jobs"]["dryrun-shard"]["steps"] if isinstance(s, dict)]


def _would_run(condition: str, *, matched: str, job_failed: bool) -> bool:
    """Evaluate an Actions ``if:`` the way the runner would.

    Only the forms in ``_KNOWN_CONDITIONS`` are handled. ``matched`` is the raw
    output value — ``""`` models a ``pin`` step that died before writing one.
    """
    condition = condition.strip()
    if condition == "":
        return not job_failed
    if condition == "always()":
        return True
    if condition == "failure()":
        return job_failed
    if condition == "steps.pin.outputs.matched == 'true'":
        return matched == "true" and not job_failed
    raise AssertionError(f"unhandled workflow condition: {condition!r}")


def _run_pin(tmp_path: Path, expected: str, actual: str) -> str:
    """Execute the real pin script; return the ``matched`` value it wrote."""
    out = tmp_path / "github_output.txt"
    out.touch()
    pin_main(
        [
            "--expected-sha",
            expected,
            "--actual-sha",
            actual,
            "--shard",
            "4/6",
            "--skip-summary-json",
            str(tmp_path / "summary.json"),
            "--github-output",
            str(out),
        ]
    )
    values: dict[str, str] = {}
    for line in out.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep:
            values[key] = value
    return values.get("matched", "")


def _privileged_steps() -> list[dict]:
    """Steps that write a cache or execute repo code — the poisonable surface."""
    privileged = []
    for step in _shard_steps():
        if step.get("id") == "pin":
            continue
        uses = str(step.get("uses", ""))
        run = str(step.get("run", ""))
        if uses.startswith(("actions/checkout@", "actions/upload-artifact@")):
            continue
        if uses or run:
            privileged.append(step)
    return privileged


def test_every_gate_expression_is_understood() -> None:
    unknown = {
        str(s.get("if", "")).strip()
        for s in _shard_steps()
        if str(s.get("if", "")).strip() not in _KNOWN_CONDITIONS
    }
    assert not unknown, f"evaluator does not model these conditions: {unknown}"


def test_shard_has_privileged_steps_to_protect() -> None:
    # Sanity: without this, every assertion below passes vacuously.
    assert len(_privileged_steps()) >= 3


def test_matching_sha_lets_every_privileged_step_run(tmp_path: Path) -> None:
    matched = _run_pin(tmp_path, _RESOLVED_SHA, _RESOLVED_SHA)
    assert matched == "true"
    for step in _privileged_steps():
        assert _would_run(str(step.get("if", "")), matched=matched, job_failed=False), (
            f"step blocked on the happy path: {step}"
        )


def test_advanced_staging_skips_every_privileged_step(tmp_path: Path) -> None:
    matched = _run_pin(tmp_path, _RESOLVED_SHA, _ADVANCED_SHA)
    assert matched == "false"
    for step in _privileged_steps():
        assert not _would_run(
            str(step.get("if", "")), matched=matched, job_failed=False
        ), f"step ran on an unasserted commit: {step}"


@pytest.mark.parametrize("matched", ["", "false", "TRUE", "1", "yes"])
def test_only_the_literal_true_unlocks_privileged_steps(matched: str) -> None:
    # A crashed pin step leaves the output unset (""); anything that is not the
    # exact string the gate compares against must fail closed.
    for step in _privileged_steps():
        assert not _would_run(str(step.get("if", "")), matched=matched, job_failed=False)


def test_a_skipped_shard_still_uploads_its_summary(tmp_path: Path) -> None:
    # The skip marker only reaches the reporter if the upload step is ungated.
    matched = _run_pin(tmp_path, _RESOLVED_SHA, _ADVANCED_SHA)
    upload = next(
        s
        for s in _shard_steps()
        if str(s.get("uses", "")).startswith("actions/upload-artifact@")
        and "summary" in str(s.get("name", "")).lower()
    )
    assert _would_run(str(upload.get("if", "")), matched=matched, job_failed=False)
    assert (tmp_path / "summary.json").is_file()


def test_shard_checkout_ref_never_returns_to_a_job_output() -> None:
    # The literal alert-#108 shape: a `needs.*.outputs.*` ref in this job.
    for step in _shard_steps():
        if str(step.get("uses", "")).startswith("actions/checkout@"):
            ref = str((step.get("with") or {}).get("ref", ""))
            assert "needs." not in ref and "${{" not in ref
