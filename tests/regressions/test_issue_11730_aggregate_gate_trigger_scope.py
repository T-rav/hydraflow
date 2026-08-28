"""#11730 — the suite-hygiene ratchet could be breached without any gate running.

Three PRs, each green on its own checks, summed to
``parametrize copies 413 > baseline 412`` on ``origin/staging`` and blocked
every open PR for hours. Two independent mechanisms let that happen, and this
file proves the fix against both by reconstructing the exact failure rather
than describing it.

**Mechanism 2 — scoped by PATH.** The gate's subject is every pytest-collected
module under ``tests/``. Its triggers are paths-filters, which are subsets of
the repo by construction. ``core_python`` carries ``predicate-quantifier:
every`` with ``!tests/regressions/**``, ``!tests/scenarios/**`` and
``!tests/sandbox_scenarios/**``; the ``arch`` filter restores
``tests/architecture/**`` but not those three. So a change confined to
``tests/regressions/`` moves the count the ratchet gates on, and before this
fix **no lane that reads the whole-``tests/`` aggregate would run**.

**Mechanism 1 — scoped by BASE.** ``strict_required_status_checks_policy`` is
false on both rulesets, so a PR's checks are evaluated against whatever base it
branched from. Even a perfectly triggered gate never sees the merged result.
Closed here by the same lane running on ``push`` to the protected branches;
asserted in ``tests/architecture/test_aggregate_gate_trigger_scope.py``.

**Vacuity.** The gate compares counts to marks, and every count over an empty
tree is under every mark, so a scan that collected nothing passed serenely.
That is the same shape as the trigger bug — silence read as safety — so it is
proven here too.

The paths-filter evaluator below is a small reimplementation of picomatch's
subset that ``dorny/paths-filter`` uses. It is exercised against known cases in
``test_the_glob_matcher_is_faithful`` so a broken matcher cannot make the
proofs below pass by accident.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from erosion.suite_hygiene import collect_tests, compute
from erosion.suite_hygiene_baseline import SuiteHygieneBaseline, exceeded
from tests.architecture.aggregate_gate_registry import LANE_JOB, makefile_lane_paths

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CI_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"

#: The gate whose breach started this: subject is all of ``tests/``.
_SUBJECT_GATE = "tests/architecture/test_suite_hygiene_ratchet.py"

#: A file inside the subject (all of ``tests/``) and outside every trigger that
#: existed before #11730 — the exact shape of PR #11714's contribution.
_PROBE_PATH = "tests/regressions/test_issue_11730_probe.py"

#: Three test functions with identical normalized bodies in one file: one
#: parametrize group, worth +2 copies to the count the ratchet gates on.
_THREE_COPIES = """
def test_alpha():
    value = compute_thing("a")
    assert value == "a"


def test_beta():
    value = compute_thing("b")
    assert value == "b"


def test_gamma():
    value = compute_thing("c")
    assert value == "c"
"""


# --------------------------------------------------------------------------
# A faithful-enough picomatch subset
# --------------------------------------------------------------------------


def _glob_to_regex(glob: str) -> re.Pattern[str]:
    out: list[str] = []
    i = 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out.append("(?:[^/]+/)*")
            i += 3
        elif glob.startswith("**", i):
            out.append(".*")
            i += 2
        elif glob[i] == "*":
            out.append("[^/]*")
            i += 1
        elif glob[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(glob[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def _matches(glob: str, path: str) -> bool:
    return bool(_glob_to_regex(glob).match(path))


def _expand_braces(pattern: str) -> list[str]:
    """Expand a single top-level ``{a,b,c}`` group; ``core_python`` needs exactly this."""
    match = re.fullmatch(r"\{([^{}]*)\}", pattern)
    return match.group(1).split(",") if match else [pattern]


# --------------------------------------------------------------------------
# Reading ci.yml the way GitHub would
# --------------------------------------------------------------------------


def _ci() -> dict:
    return yaml.safe_load(_CI_PATH.read_text(encoding="utf-8"))


def _filter_steps() -> dict[str, dict[str, list[str]]]:
    """``{step_id: {filter_name: [patterns]}}`` for both paths-filter steps."""
    steps = _ci()["jobs"]["changes"]["steps"]
    out: dict[str, dict[str, list[str]]] = {}
    for step in steps:
        if not str(step.get("uses", "")).startswith("dorny/paths-filter"):
            continue
        parsed = yaml.safe_load(step["with"]["filters"])
        out[step["id"]] = {name: list(globs) for name, globs in parsed.items()}
    assert {"filter", "core_filter"} <= set(out), (
        f"expected both paths-filter steps in ci.yml, found {sorted(out)} — "
        "the parse is broken and every proof below would be vacuous"
    )
    return out


def _filter_outputs(changed: str) -> dict[str, bool]:
    """Every ``changes`` job output, evaluated for a diff of exactly one file."""
    steps = _filter_steps()
    outputs: dict[str, bool] = {}
    for name, patterns in steps["filter"].items():
        # Default quantifier `some`: any glob matching the file is enough.
        assert not any(p.startswith("!") for p in patterns), (
            f"filter `{name}` grew a negation under the default quantifier, "
            "where `!glob` matches every file NOT under glob (#9908). This "
            "evaluator assumes positive globs only in that step."
        )
        outputs[name] = any(_matches(p, changed) for p in patterns)
    for name, patterns in steps["core_filter"].items():
        # `predicate-quantifier: every`: the file must satisfy ALL patterns.
        def _ok(pattern: str) -> bool:
            if pattern.startswith("!"):
                return not _matches(pattern[1:], changed)
            return any(_matches(g, changed) for g in _expand_braces(pattern))

        outputs[name] = all(_ok(p) for p in patterns)
    return outputs


_OUTPUT_REF = re.compile(
    r"needs\.changes\.outputs\.([A-Za-z_][A-Za-z0-9_]*)\s*==\s*'true'"
)


def _job_fires(job: dict, changed: str) -> bool:
    """Would this job run for a diff of exactly *changed*?"""
    condition = job.get("if")
    if condition is None:
        return True  # ungated: no filter can shrink it
    referenced = _OUTPUT_REF.findall(str(condition))
    assert referenced, (
        f"job condition {condition!r} references no changes output; this "
        "evaluator only models path-gated jobs and must not guess at others"
    )
    outputs = _filter_outputs(changed)
    return any(outputs[name] for name in referenced)


def _pytest_targets(job: dict) -> tuple[list[str], list[str]]:
    """``(positional paths, --ignore paths)`` across every ``run:`` step of a job."""
    positionals: list[str] = []
    ignores: list[str] = []
    for step in job.get("steps") or []:
        command = str(step.get("run", ""))
        if "make aggregate-ratchets" in command:
            positionals.extend(makefile_lane_paths())
        for chunk in command.split("pytest ")[1:]:
            for token in chunk.split():
                if token.startswith("--ignore="):
                    ignores.append(token.removeprefix("--ignore="))
                elif token.startswith("tests/"):
                    positionals.append(token)
                elif token.startswith("-"):
                    continue
                else:
                    break
    return positionals, ignores


def _collects(job: dict, test_path: str) -> bool:
    """Would this job's pytest invocations collect *test_path*?"""

    def _covers(target: str) -> bool:
        target = target.rstrip("/")
        return test_path == target or test_path.startswith(f"{target}/")

    positionals, ignores = _pytest_targets(job)
    return any(_covers(p) for p in positionals) and not any(_covers(i) for i in ignores)


def _jobs_that_would_measure(changed: str, gate: str) -> set[str]:
    """CI jobs that both FIRE for *changed* and COLLECT *gate*."""
    return {
        key
        for key, job in _ci()["jobs"].items()
        if _collects(job, gate) and _job_fires(job, changed)
    }


# --------------------------------------------------------------------------
# The evaluator must be trustworthy before its verdicts mean anything
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("glob", "path", "expected"),
    [
        pytest.param(
            "tests/**", "tests/regressions/test_x.py", True, id="globstar-deep"
        ),
        pytest.param("tests/**", "tests/test_x.py", True, id="globstar-shallow"),
        pytest.param("tests/**", "src/x.py", False, id="globstar-miss"),
        pytest.param("src/**/*.py", "src/x.py", True, id="zero-segment-globstar"),
        pytest.param("src/**/*.py", "src/a/b.py", True, id="multi-segment-globstar"),
        pytest.param("src/**/*.py", "src/a/b.md", False, id="extension-miss"),
        pytest.param(
            "tests/architecture/**",
            "tests/regressions/t.py",
            False,
            id="sibling-dir-miss",
        ),
        pytest.param(
            "tests/test_gateway_*.py",
            "tests/test_gateway_a.py",
            True,
            id="star-in-name",
        ),
        pytest.param(
            "tests/test_gateway_*.py",
            "tests/sub/test_gateway_a.py",
            False,
            id="star-stops-at-slash",
        ),
        pytest.param("Makefile", "Makefile", True, id="literal"),
        pytest.param("Makefile", "Makefile.bak", False, id="literal-anchored"),
    ],
)
def test_the_glob_matcher_is_faithful(glob: str, path: str, expected: bool) -> None:
    """Guard the guard: a permissive matcher would make every proof below vacuous."""
    assert _matches(glob, path) is expected


# --------------------------------------------------------------------------
# Mechanism 2: the breach is real, and the fix now measures it
# --------------------------------------------------------------------------


def test_a_regressions_only_change_moves_the_gated_count() -> None:
    """The exact breach: +2 parametrize copies from a file outside every old trigger.

    Marked against the LIVE count rather than the committed baseline, because
    the committed mark drifts with every pruning pass and the property under
    test does not: whatever the mark was before the change, this change crosses
    it.
    """
    live_sources = collect_tests(_REPO_ROOT / "tests")
    live = compute(live_sources)
    mark_at_head = SuiteHygieneBaseline(
        parametrize_copies=live.parametrize_copies,
        cross_file_duplicates=len(live.cross_file_duplicates),
    )

    breached = compute({**live_sources, _PROBE_PATH: _THREE_COPIES})

    assert breached.parametrize_copies == live.parametrize_copies + 2, (
        "the probe no longer adds a parametrize group — erosion.suite_hygiene "
        "normalization changed, so this reconstruction has stopped "
        "reconstructing anything"
    )
    assert exceeded(breached, mark_at_head), (
        "a three-copy group added under tests/regressions/ did not breach the "
        "mark it was measured against — the gate this issue is about has "
        "stopped gating"
    )


def test_some_lane_measures_the_whole_tests_tree_for_a_regressions_only_change() -> (
    None
):
    """The fix, stated as the property that was false before it (#11730).

    Before: for a diff confined to ``tests/regressions/``, this set was EMPTY.
    ``Architecture Check`` was skipped (the ``arch`` filter does not list
    ``tests/regressions/**``), ``Tests`` was skipped (``core_python`` negates
    it), and ``Regression Tests`` runs ``pytest tests/regressions/``, which
    does not collect the whole-tree gate. The count moved unmeasured.

    Deliberately asserted as "at least one lane", not "the lane": if someone
    later widens ``core_python`` so ``Tests`` covers it too, the subject is
    still measured and this should stay green.
    """
    measuring = _jobs_that_would_measure(_PROBE_PATH, _SUBJECT_GATE)

    assert measuring, (
        f"no CI job both fires for a change to {_PROBE_PATH} and collects "
        f"{_SUBJECT_GATE}. A whole-tests/-tree aggregate can once again be "
        "moved with no gate watching — this is #11730, reopened."
    )
    assert LANE_JOB in measuring, (
        f"the ungated `{LANE_JOB}` lane is not among the jobs that measure "
        f"{_SUBJECT_GATE} ({sorted(measuring)}). Whatever else covers it today "
        "is path-gated and will develop the same hole."
    )


def test_the_lane_covers_the_whole_subject_not_just_the_regressions_hole() -> None:
    """Every corner of ``tests/`` reaches the lane, including the other two negations."""
    for changed in (
        "tests/test_top_level.py",
        "tests/regressions/test_x.py",
        "tests/scenarios/test_x.py",
        "tests/sandbox_scenarios/test_x.py",
        "tests/architecture/test_x.py",
    ):
        assert LANE_JOB in _jobs_that_would_measure(changed, _SUBJECT_GATE), (
            f"a change to {changed} does not reach the ungated lane — the "
            "trigger is narrower than the subject somewhere it should not be"
        )


# --------------------------------------------------------------------------
# Vacuity: a run that measures nothing must not pass
# --------------------------------------------------------------------------


def test_an_empty_scan_would_pass_the_ratchet_but_fails_the_subject_check(
    tmp_path: Path,
) -> None:
    """Why ``test_the_scan_actually_has_a_subject`` exists.

    Both halves of the ratchet are ``count > mark``, and zero is under every
    mark. So the ratchet ALONE reports green against an empty tree — the
    failure this asserts, and the reason the subject check is a separate,
    louder assertion rather than a comment.
    """
    empty = tmp_path / "tests"
    empty.mkdir()

    finding = compute(collect_tests(empty))
    mark = SuiteHygieneBaseline(parametrize_copies=412, cross_file_duplicates=21)

    assert finding.total_files == 0
    assert finding.total_tests == 0
    assert not exceeded(finding, mark), (
        "an empty tree now exceeds a mark — if erosion.suite_hygiene gained a "
        "floor of its own, this reconstruction is stale"
    )
    assert not (finding.total_files and finding.total_tests), (
        "the subject check in test_suite_hygiene_ratchet.py asserts exactly "
        "this conjunction; it must be false for an empty scan or the gate "
        "would still pass while measuring nothing"
    )


def test_a_missing_mark_would_disable_the_ratchet_silently() -> None:
    """The other vacuity: no mark means ``exceeded`` never speaks."""
    huge = compute({_PROBE_PATH: _THREE_COPIES * 40})
    assert huge.parametrize_copies > 0

    assert not exceeded(huge, SuiteHygieneBaseline()), (
        "a baseline with no marks now reports a breach — if that changed, the "
        "`parametrize_copies is not None` assertion in the gate is redundant "
        "and should be removed rather than left as decoration"
    )
