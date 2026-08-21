"""Shape pins for the staging RC dry-run shard checkout (#11518).

CodeQL alert #108 (``actions/cache-poisoning/poisonable-step``) fired because
``dryrun-shard`` checked out ``ref: ${{ needs.resolve.outputs.sha }}`` — a job
output — and then ran cache-writing steps (``pip install``, ``docker compose
build``) in a privileged, default-branch context. The fix checks out the literal
protected branch and asserts the SHA in-job via
``scripts/staging_rc_dryrun_pin.py``.

Two layers guard that, and they are deliberately different:

* the *behaviour* of the assertion is executed in ``tests/test_staging_rc_
  dryrun_pin.py`` — real ``$GITHUB_OUTPUT`` files, real exit codes;
* the *wiring* that makes the workflow actually use it is pinned here, derived
  from the YAML rather than restated, so a step added later without the gate
  fails instead of quietly running unasserted code.

The fleet sweep at the bottom stops the same shape reappearing in a new
workflow.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
DRYRUN_WORKFLOW = WORKFLOW_DIR / "staging-rc-dryrun.yml"

#: The literal ref the shard is allowed to check out. ``staging`` is the
#: protected integration branch of the two-tier model (ADR-0042).
PROTECTED_REF = "staging"

#: The exact fail-safe guard every gated step carries. Positive equality against
#: a literal means an *unset* output (crashed pin step) skips rather than runs.
PIN_GUARD = "steps.pin.outputs.matched == 'true'"

PIN_SCRIPT_PATH = "scripts/staging_rc_dryrun_pin.py"

#: ``run:`` fragments that populate or write a build cache the next run reuses.
CACHE_WRITING_RUN_MARKERS = (
    "pip install",
    "uv pip install",
    "uv sync",
    "npm ci",
    "npm install",
    "yarn install",
    "poetry install",
    "docker build",
    "docker compose",
    "docker-compose",
    "make deps",
)
#: ``uses:`` prefixes that write a cache unconditionally.
CACHE_WRITING_ACTIONS = ("actions/cache",)
#: Inputs that turn a setup-* action into a cache writer.
CACHE_ENABLING_INPUTS = ("cache", "enable-cache", "cache-dependency-path")


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _triggers(workflow: dict) -> dict:
    """YAML 1.1 coerces the bare key ``on`` to boolean ``True`` — read both."""
    raw = workflow.get("on")
    if raw is None:
        raw = workflow.get(True)
    return raw if isinstance(raw, dict) else {}


def _steps(job: dict) -> list[dict]:
    return [s for s in job.get("steps", []) or [] if isinstance(s, dict)]


def _is_checkout(step: dict) -> bool:
    return str(step.get("uses", "")).startswith("actions/checkout@")


def _checkout_ref(step: dict) -> str:
    return str((step.get("with") or {}).get("ref", ""))


def _is_cache_writing(step: dict) -> bool:
    uses = str(step.get("uses", ""))
    if uses.startswith(CACHE_WRITING_ACTIONS):
        return True
    if "setup-" in uses:
        inputs = step.get("with") or {}
        if any(key in inputs for key in CACHE_ENABLING_INPUTS):
            return True
    run = str(step.get("run", ""))
    return any(marker in run for marker in CACHE_WRITING_RUN_MARKERS)


def _flag_value(run: str, flag: str) -> str | None:
    """Value passed to ``--flag`` in a ``run:`` body, to the line continuation.

    Not ``\\S+``: an argument may legitimately contain spaces once a ``${{ }}``
    expression is interpolated into it (``${{ matrix.shard }}/6``).
    """
    match = re.search(rf"{re.escape(flag)}\s+(.+?)\s*(?:\\\s*)?$", run, re.MULTILINE)
    return match.group(1) if match else None


def _is_matrix_sharded(job: dict) -> bool:
    return "matrix" in (job.get("strategy") or {})


def _job_line_span(raw: str, job_name: str) -> tuple[int, int]:
    """First and last raw-line index of ``job_name``'s block in a workflow."""
    lines = raw.splitlines()
    start = next(
        (i for i, ln in enumerate(lines) if ln.rstrip() == f"  {job_name}:"), -1
    )
    assert start >= 0, f"job {job_name!r} not found in raw workflow text"
    end = next(
        (
            i
            for i in range(start + 1, len(lines))
            if lines[i].strip() and not lines[i].startswith("   ")
        ),
        len(lines),
    )
    return start, end


def _trust_marked_checkouts(raw: str, span: tuple[int, int]) -> list[bool]:
    """For each checkout step in the span, whether a ``# TRUST:`` block precedes it.

    Scans raw text, not the parsed tree: comments are the whole point of the
    marker and ``yaml.safe_load`` throws them away.
    """
    lines = raw.splitlines()
    start, end = span
    marked: list[bool] = []
    for idx in range(start, end):
        if not re.match(r"^\s*-\s+uses:\s*actions/checkout@", lines[idx]):
            continue
        found = False
        cursor = idx - 1
        while cursor >= start and lines[cursor].strip().startswith("#"):
            if lines[cursor].strip().startswith("# TRUST:"):
                found = True
            cursor -= 1
        marked.append(found)
    return marked


@pytest.fixture(scope="module")
def workflow() -> dict:
    return _load(DRYRUN_WORKFLOW)


@pytest.fixture(scope="module")
def raw_workflow() -> str:
    return DRYRUN_WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def shard_steps(workflow: dict) -> list[dict]:
    return _steps(workflow["jobs"]["dryrun-shard"])


@pytest.fixture(scope="module")
def pin_step(shard_steps: list[dict]) -> dict:
    matches = [s for s in shard_steps if s.get("id") == "pin"]
    assert len(matches) == 1, "expected exactly one step with id: pin"
    return matches[0]


class TestPrivilegedContext:
    """Why the alert exists: this workflow runs with default-branch privilege."""

    def test_runs_only_on_schedule_and_manual_dispatch(self, workflow: dict) -> None:
        assert set(_triggers(workflow)) == {"schedule", "workflow_dispatch"}

    def test_shard_job_is_matrix_sharded_and_cache_writing(
        self, workflow: dict, shard_steps: list[dict]
    ) -> None:
        assert _is_matrix_sharded(workflow["jobs"]["dryrun-shard"])
        assert any(_is_cache_writing(s) for s in shard_steps)


class TestShardCheckout:
    def test_shard_checks_out_the_literal_protected_branch(
        self, shard_steps: list[dict]
    ) -> None:
        checkouts = [s for s in shard_steps if _is_checkout(s)]
        assert len(checkouts) == 1
        assert _checkout_ref(checkouts[0]) == PROTECTED_REF

    def test_shard_checkout_ref_is_not_an_expression(
        self, shard_steps: list[dict]
    ) -> None:
        # The exact regression: `ref: ${{ needs.resolve.outputs.sha }}`.
        for step in shard_steps:
            if _is_checkout(step):
                assert "${{" not in _checkout_ref(step)

    def test_trust_comment_documents_the_shard_checkout(
        self, raw_workflow: str
    ) -> None:
        span = _job_line_span(raw_workflow, "dryrun-shard")
        marked = _trust_marked_checkouts(raw_workflow, span)
        assert marked and all(marked)


class TestPinStepWiring:
    def test_pin_step_invokes_the_pin_script(self, pin_step: dict) -> None:
        assert PIN_SCRIPT_PATH in str(pin_step.get("run", ""))

    def test_pin_script_exists(self) -> None:
        assert (REPO_ROOT / PIN_SCRIPT_PATH).is_file()

    def test_resolved_sha_reaches_the_script_through_the_environment(
        self, pin_step: dict
    ) -> None:
        # Via `env:` rather than inline `${{ }}` in `run:` — the value is a job
        # output, and interpolating one straight into a shell body is the
        # script-injection shape CodeQL flags next.
        env = pin_step.get("env") or {}
        names = [k for k, v in env.items() if "needs.resolve.outputs.sha" in str(v)]
        assert len(names) == 1, f"expected one resolved-SHA env var, got {env}"
        run = str(pin_step["run"])
        assert f'--expected-sha "${names[0]}"' in run
        assert "${{ needs.resolve.outputs.sha }}" not in run

    def test_pin_step_uses_system_python_before_setup_python(
        self, pin_step: dict, shard_steps: list[dict]
    ) -> None:
        assert "python3 " in str(pin_step["run"])
        setup = next(
            i
            for i, s in enumerate(shard_steps)
            if str(s.get("uses", "")).startswith("actions/setup-python@")
        )
        assert shard_steps.index(pin_step) < setup

    def test_shard_label_passed_to_the_pin_matches_the_run_label(
        self, pin_step: dict, shard_steps: list[dict]
    ) -> None:
        env = pin_step.get("env") or {}
        labels = {v for v in env.values() if "matrix.shard" in str(v)}
        run_all = next(
            s for s in shard_steps if "sandbox_scenario.py run-all" in str(s.get("run"))
        )
        shard_arg = _flag_value(str(run_all["run"]), "--shard")
        assert shard_arg is not None
        assert labels == {shard_arg}

    def test_skip_marker_path_is_the_path_that_gets_uploaded(
        self, pin_step: dict, shard_steps: list[dict]
    ) -> None:
        # If these drift apart, a skipped shard uploads nothing and the reporter
        # silently scans zero summaries instead of a zero-failure marker.
        marker = _flag_value(str(pin_step["run"]), "--skip-summary-json")
        assert marker is not None
        upload = next(
            s
            for s in shard_steps
            if str(s.get("uses", "")).startswith("actions/upload-artifact@")
            and "summary" in str(s.get("name", "")).lower()
        )
        assert (upload.get("with") or {}).get("path") == marker

    def test_summary_upload_is_unconditional_so_a_skip_still_reports(
        self, shard_steps: list[dict]
    ) -> None:
        upload = next(
            s
            for s in shard_steps
            if str(s.get("uses", "")).startswith("actions/upload-artifact@")
            and "summary" in str(s.get("name", "")).lower()
        )
        assert str(upload.get("if", "")).strip() == "always()"
        assert PIN_GUARD not in str(upload.get("if", ""))


class TestPinGating:
    """No cache-writing or code-executing step may run on an unasserted SHA."""

    def _gated(self, step: dict) -> bool:
        return PIN_GUARD in str(step.get("if", ""))

    def test_every_cache_writing_step_is_pin_gated(
        self, shard_steps: list[dict]
    ) -> None:
        cache_steps = [s for s in shard_steps if _is_cache_writing(s)]
        assert cache_steps, "sanity: the shard should have cache-writing steps"
        ungated = [s for s in cache_steps if not self._gated(s)]
        assert not ungated, f"cache-writing steps missing the pin gate: {ungated}"

    def test_the_scenario_run_is_pin_gated(self, shard_steps: list[dict]) -> None:
        run_all = next(
            s for s in shard_steps if "sandbox_scenario.py run-all" in str(s.get("run"))
        )
        assert self._gated(run_all)

    def test_only_checkout_pin_and_uploads_run_without_the_gate(
        self, shard_steps: list[dict], pin_step: dict
    ) -> None:
        # Derived, not restated: anything new that is neither the checkout, the
        # pin itself, nor an artifact upload must carry the gate.
        for step in shard_steps:
            if step is pin_step or _is_checkout(step):
                continue
            if str(step.get("uses", "")).startswith("actions/upload-artifact@"):
                continue
            assert self._gated(step), f"ungated shard step: {step}"

    def test_gate_is_positive_equality_so_an_unset_output_skips(
        self, shard_steps: list[dict]
    ) -> None:
        for step in shard_steps:
            condition = str(step.get("if", ""))
            if "steps.pin.outputs.matched" not in condition:
                continue
            assert PIN_GUARD in condition
            assert "!=" not in condition

    def test_pin_runs_before_every_gated_step(
        self, shard_steps: list[dict], pin_step: dict
    ) -> None:
        pin_index = shard_steps.index(pin_step)
        gated = [i for i, s in enumerate(shard_steps) if self._gated(s)]
        assert gated and min(gated) > pin_index


class TestReportJobStaysPinnedToTheTestedCommit:
    """Guard against over-fixing: the reporter must name one exact commit."""

    def test_report_checks_out_the_resolved_sha(self, workflow: dict) -> None:
        report = workflow["jobs"]["report"]
        checkouts = [s for s in _steps(report) if _is_checkout(s)]
        assert len(checkouts) == 1
        assert "needs.resolve.outputs.sha" in _checkout_ref(checkouts[0])

    def test_report_job_writes_no_cache(self, workflow: dict) -> None:
        # This is *why* the expression ref is safe to keep there.
        assert not any(_is_cache_writing(s) for s in _steps(workflow["jobs"]["report"]))

    def test_report_checkout_records_why_its_ref_is_trusted(
        self, raw_workflow: str
    ) -> None:
        # The kept exception needs the same machine-checkable justification as
        # the fixed one, so a future reader can tell "reviewed" from "missed".
        marked = _trust_marked_checkouts(
            raw_workflow, _job_line_span(raw_workflow, "report")
        )
        assert marked and all(marked)


class TestFleetSweep:
    """Any sharded, cache-writing job in the fleet must justify its ref."""

    @staticmethod
    def _offenders() -> list[str]:
        offenders: list[str] = []
        for path in sorted(WORKFLOW_DIR.glob("*.yml")):
            raw = path.read_text(encoding="utf-8")
            workflow = _load(path)
            for job_name, job in (workflow.get("jobs") or {}).items():
                if not isinstance(job, dict):
                    continue
                if not (
                    _is_matrix_sharded(job) and any(map(_is_cache_writing, _steps(job)))
                ):
                    continue
                expression_refs = [
                    s
                    for s in _steps(job)
                    if _is_checkout(s) and "${{" in _checkout_ref(s)
                ]
                if not expression_refs:
                    continue
                span = _job_line_span(raw, job_name)
                if not all(_trust_marked_checkouts(raw, span)):
                    offenders.append(f"{path.name}:{job_name}")
        return offenders

    def test_sweep_covers_the_shard_job(self) -> None:
        # Sanity: the classifier must actually select the job we care about,
        # otherwise the sweep below passes vacuously.
        workflow = _load(DRYRUN_WORKFLOW)
        job = workflow["jobs"]["dryrun-shard"]
        assert _is_matrix_sharded(job) and any(map(_is_cache_writing, _steps(job)))

    def test_no_sharded_cache_writing_job_checks_out_an_unjustified_ref(
        self,
    ) -> None:
        assert self._offenders() == []
