"""Realistic-agent scenarios — drive real AgentRunner via FakeSubprocessRunner.

FakeWorkspace creates worktrees at ``tmp_path / "worktrees" / "issue-{N}"``.
Each test initialises that directory as a real git repository (with an
``origin/main`` ref) so that AgentRunner._count_commits sees actual commits
written by FakeDocker.script_run_with_commits.

FakeSubprocessRunner.run_simple dispatches ``git`` commands to the real host;
other commands (agent CLI, ``make``) go through FakeDocker so tests can script
their outcomes.
"""

from __future__ import annotations

import pytest

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.git_worktree_fixture import init_test_worktree

pytestmark = pytest.mark.scenario


async def test_A0_happy_path_realistic_agent(tmp_path) -> None:
    """A0: Single issue flows through real AgentRunner and gets merged.

    The FakeDocker script commits a file into the worktree so that
    AgentRunner._count_commits sees 1 commit ahead of origin/main, which
    lets _verify_result pass the commit-check gate.  All other quality checks
    (the implement gate, skills, pre-quality review) use FakeDocker defaults which
    return success with an empty transcript, causing skill parsers to default
    to passed=True.
    """
    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])

    # FakeWorkspace creates the dir at tmp_path / "worktrees" / "issue-1".
    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    init_test_worktree(worktree_cwd, branch="agent/issue-1")

    world.docker.script_run_with_commits(
        events=[{"type": "result", "success": True, "exit_code": 0}],
        commits=[("x.py", "changed")],
        cwd=worktree_cwd,
    )

    result = await world.run_pipeline()

    outcome = result.issue(1)
    assert outcome.merged, (
        f"expected merged=True; got outcome={outcome!r}; "
        f"worker_result={outcome.worker_result!r}; "
        f"docker_invocations={len(world.docker.invocations)}"
    )
    assert len(world.docker.invocations) >= 1


async def test_A1_docker_timeout_fails_issue_no_retry(tmp_path) -> None:
    """A1: Timeout on first run — documents production timeout behaviour.

    Production does NOT retry on timeout; the issue fails.  This test asserts
    the observable outcome: at least 1 Docker invocation and a non-merged
    (failed) outcome for the issue, matching real production behaviour.
    """
    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])

    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    init_test_worktree(worktree_cwd, branch="agent/issue-1")

    world.docker.fail_next(kind="timeout")

    result = await world.run_pipeline()

    # Production does not retry after a timeout — issue fails at implement.
    assert len(world.docker.invocations) >= 1
    # Worker result records the failure
    wr = result.issue(1).worker_result
    assert wr is not None
    assert wr.success is False


async def test_A2_oom_fails_issue(tmp_path) -> None:
    """A2: OOM (exit_code=137) causes the agent to fail.

    FakeDocker returns exit_code=137 which stream_claude_process converts
    to a completed transcript.  AgentRunner._count_commits then returns 0
    (no commits were made) causing _verify_result to fail with
    "No commits found on branch".
    """
    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])

    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    init_test_worktree(worktree_cwd, branch="agent/issue-1")

    world.docker.fail_next(kind="oom")

    result = await world.run_pipeline()

    outcome = result.issue(1)
    assert not outcome.merged
    wr = outcome.worker_result
    assert wr is not None
    assert wr.success is False


async def test_A3_malformed_stream_recovers_to_failure(tmp_path) -> None:
    """A3: Malformed stream (garbage events + exit_code=1) causes failure.

    The garbage event type is ignored by StreamParser; the trailing
    result event signals failure.  No commits are made so _count_commits
    returns 0 and the issue fails.
    """
    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])

    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    init_test_worktree(worktree_cwd, branch="agent/issue-1")

    world.docker.fail_next(kind="malformed_stream")

    result = await world.run_pipeline()

    outcome = result.issue(1)
    assert not outcome.merged
    wr = outcome.worker_result
    assert wr is not None
    assert wr.success is False


async def test_A4_unknown_event_type_ignored_stream_continues(tmp_path) -> None:
    """A4: Unknown event type (auth_retry_required) is ignored by StreamParser.

    Production StreamParser does not recognise ``auth_retry_required`` as a
    known event type, so it is silently skipped.  The subsequent
    ``{"type": "result", "success": True, "exit_code": 0}`` event completes
    the stream normally.  Because the commit hook runs before the events are
    yielded, a real commit exists and the issue can be merged.

    This test verifies that an unknown event type does NOT crash the pipeline
    and that subsequent events are processed correctly.
    """
    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])

    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    init_test_worktree(worktree_cwd, branch="agent/issue-1")

    world.docker.script_run_with_commits(
        events=[
            {"type": "auth_retry_required"},
            {"type": "result", "success": True, "exit_code": 0},
        ],
        commits=[("x.py", "done")],
        cwd=worktree_cwd,
    )

    result = await world.run_pipeline()

    outcome = result.issue(1)
    # Minimum assertion: at least one Docker invocation, pipeline did not crash
    assert len(world.docker.invocations) >= 1
    assert outcome.worker_result is not None
    # The unknown event is ignored; the trailing success result is processed
    # and the issue should be merged (same as A0 happy path).
    assert outcome.merged, (
        f"A4: expected merged=True after auth_retry_required + result:success; "
        f"worker_result={outcome.worker_result!r}"
    )


async def test_A5_token_budget_exceeded_halts_implement(tmp_path) -> None:
    """Stream-level ``budget_exceeded`` event + failure result → issue fails.

    This is distinct from ``FakeLLM.set_token_budget`` (which gates scripted
    planner/reviewer turns). In realistic-agent mode, the scripted
    _FakeAgentRunner is replaced by the real AgentRunner, so the FakeLLM
    budget does not gate the implement path. Scenarios that need implement-
    level budget enforcement must use FakeDocker stream events like this one.
    """
    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])

    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    init_test_worktree(worktree_cwd)

    world.docker.script_run(
        [
            {"type": "budget_exceeded", "tokens_used": 200_000},
            {"type": "result", "success": False, "exit_code": 1},
        ]
    )

    result = await world.run_pipeline()

    assert not result.issue(1).merged
    wr = result.issue(1).worker_result
    assert wr is not None
    assert wr.success is False


async def test_A6_github_rate_limit_at_triage_halts_pipeline(tmp_path) -> None:
    """Rate-limit armed before triage halts the pipeline at the earliest GitHub call (find_existing_issue in triage's dup-check), not at create_pr.

    `fail_service("github")` sets remaining=0.  The first GitHub call
    (find_existing_issue in the triage duplicate-check) raises RateLimitError.
    `phase_utils.run_refilling_pool` catches non-fatal exceptions and logs
    them as warnings — it does NOT re-raise RateLimitError because it is
    outside `exception_classify.FATAL_EXCEPTIONS` (the infra-fatal trio plus
    the likely-bug class, #11618).

    Observable behavior:
    - `run_pipeline` returns normally (no raise).
    - The issue never progresses past triage → no PR is created.
    - The rate-limit counter is consumed (remaining drops to 0).
    """
    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])

    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    init_test_worktree(worktree_cwd)

    world.docker.script_run_with_commits(
        events=[{"type": "result", "success": True, "exit_code": 0}],
        commits=[("x.py", "ok")],
        cwd=worktree_cwd,
    )
    world.fail_service("github")  # arms rate-limit (remaining=0)

    # run_pipeline returns normally — the pool absorbs the RateLimitError.
    result = await world.run_pipeline()

    # No PR was created; issue never merged.
    assert world.github.pr_for_issue(1) is None
    assert not result.issue(1).merged
    # Rate-limit was armed and triggered (remaining stays at 0, not None).
    assert world.github._rate_limit_remaining == 0


async def test_A7_github_secondary_rate_limit_surfaces(tmp_path) -> None:
    """Secondary (abuse-detection) rate-limit is also absorbed by run_refilling_pool.

    `set_rate_limit_mode(remaining=0, secondary=True)` arms the fake with the
    secondary flag set.  Like A6, run_refilling_pool absorbs the error — the
    distinction between primary and secondary rate-limits is carried in the
    RateLimitError instance (secondary=True) but the pool does not propagate
    either variant.

    Observable behavior:
    - `run_pipeline` returns normally (no raise).
    - The issue never progresses → no PR is created.
    - The rate-limit mode is still armed (remaining=0, secondary=True).
    """
    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])

    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    init_test_worktree(worktree_cwd)

    world.docker.script_run_with_commits(
        events=[{"type": "result", "success": True, "exit_code": 0}],
        commits=[("x.py", "ok")],
        cwd=worktree_cwd,
    )
    world.github.set_rate_limit_mode(remaining=0, secondary=True)

    # run_pipeline returns normally — the pool absorbs the RateLimitError.
    result = await world.run_pipeline()

    assert world.github.pr_for_issue(1) is None
    assert not result.issue(1).merged
    # Secondary flag is still set; confirms secondary mode was armed.
    assert world.github._rate_limit_secondary is True
    assert world.github._rate_limit_remaining == 0


async def test_A8_find_stage_to_done_realistic_agent(tmp_path) -> None:
    """Full pipeline from hydraflow-find through triage+plan+implement+review.

    All other A-scenarios shortcut via ``labels=["hydraflow-ready"]``. This
    one proves the realistic-agent path works from the default entry point
    that production uses for new issues.

    ``add_issue`` with no ``labels`` defaults to ``["hydraflow-find"]``.
    ``run_pipeline`` seeds at stage ``"find"`` unconditionally; the triage
    phase processes the issue and FakeLLM defaults to ``ready=True`` so the
    issue progresses through plan→implement→review exactly like a
    ``hydraflow-ready`` issue.
    """
    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b")  # defaults to labels=["hydraflow-find"]

    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    init_test_worktree(worktree_cwd)

    world.docker.script_run_with_commits(
        events=[{"type": "result", "success": True, "exit_code": 0}],
        commits=[("x.py", "done")],
        cwd=worktree_cwd,
    )

    result = await world.run_pipeline()

    # Full pipeline ran and merged the issue.
    assert result.issue(1).merged
    # At least one real AgentRunner invocation occurred.
    assert len(world.docker.invocations) >= 1


async def test_A10_quality_fix_loop_retries_then_passes(tmp_path) -> None:
    """quality-lite fails → fix agent runs → second quality-lite passes.

    Proves the realistic path exercises production `AgentRunner._run_quality_fix_loop`.
    `max_quality_fix_attempts` defaults to 2 in ConfigFactory, so one retry is
    enough to pass.

    FakeDocker scripts are consumed FIFO by ALL run_agent calls (both
    create_streaming_process for agent _execute calls and run_simple for
    ``make`` calls). The post-implementation pipeline after the initial agent
    run is:

      1. Initial agent _execute (streaming) — commits broken code
      2. diff-sanity skill _execute — default success (no marker → passed)
      3. scope-check skill _execute — default success (auto-pass, no plan)
         plan-compliance is SKIPPED (empty prompt when no plan → no _execute call)
      4. test-adequacy skill _execute — default success
      5. test-adequacy's ``make coverage 0`` probe (run_simple) — default success
      6. pre-quality review _execute, attempt 1, review pass — default success
      7. pre-quality run-tool _execute, attempt 1, run_tool pass — default success
      8. First `make quality-lite` (run_simple) — FAILS with exit_code=1
      9. Quality-fix agent _execute (streaming) — commits fix
     10. Second `make quality-lite` (run_simple) — PASSES with exit_code=0
     11. Test step (`make test`: no ``test-impacted`` target in this worktree)
         (run_simple) — default success

    The implement gate never runs the host-locked `make quality` (#11568).
    plan-compliance returns an empty prompt string when no plan is present,
    causing _run_skill to return early without calling _execute. Only 3 of the
    4 registered skills consume an agent slot; test-adequacy also spends one
    on its coverage probe. All skill/pre-quality slots must be explicitly
    queued in FIFO order so that the fail/fix scripts land in the correct
    positions.
    """
    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])
    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    init_test_worktree(worktree_cwd)

    _ok = [{"type": "result", "success": True, "exit_code": 0}]

    # 1) Initial agent run: commits broken code
    world.docker.script_run_with_commits(
        events=[{"type": "result", "success": True, "exit_code": 0}],
        commits=[("x.py", "broken")],
        cwd=worktree_cwd,
    )
    # 2–5) Three post-implementation skill _execute calls + test-adequacy's
    # ``make coverage 0`` probe — default success
    # (diff-sanity, scope-check, test-adequacy)
    # plan-compliance is skipped: returns empty prompt with no plan → no _execute
    for _ in range(4):
        world.docker.script_run(_ok)
    # 6–7) Pre-quality review loop attempt 1: review + run_tool — both default success
    world.docker.script_run(_ok)  # review pass
    world.docker.script_run(_ok)  # run_tool pass
    # 8) First `make quality-lite` via run_simple — FAILS
    world.docker.script_run([{"type": "result", "success": False, "exit_code": 1}])
    # 9) Quality-fix agent: commits the fix
    world.docker.script_run_with_commits(
        events=[{"type": "result", "success": True, "exit_code": 0}],
        commits=[("x.py", "fixed")],
        cwd=worktree_cwd,
    )
    # 10) Second `make quality-lite` via run_simple — PASSES
    world.docker.script_run(_ok)
    # 11) Test step (`make test`) — default success (queue exhausted)

    result = await world.run_pipeline()

    # Pipeline completed and merged
    assert result.issue(1).merged, (
        f"expected merged=True; outcome={result.issue(1)!r}; "
        f"docker_invocations={len(world.docker.invocations)}"
    )
    # FakeDocker invocations:
    # 1 agent + 3 skills + 1 coverage probe + 2 pre-quality + 1 quality-lite-fail
    # + 1 fix-agent + 1 quality-lite-pass + 1 test step = 11.
    assert len(world.docker.invocations) >= 11
    make_cmds = [
        inv.command for inv in world.docker.invocations if inv.command[:1] == ["make"]
    ]
    assert ["make", "quality"] not in make_cmds  # off the host lock (#11568)
    assert make_cmds.count(["make", "quality-lite"]) == 2


async def test_A11_review_fix_ci_loop_resolves(tmp_path) -> None:
    """CI fails after PR creation → fix_ci runs → CI passes → merge proceeds.

    FakeGitHub.script_ci feeds (fail, pass) to wait_for_ci. Real ReviewPhase
    wait_and_fix_ci catches the failure, invokes the scripted fix_ci (FakeLLM,
    always returns fixes_made=True), re-waits CI which now passes. Merge proceeds.

    Requires max_ci_fix_attempts=1 — the CI gate is disabled by default
    (ConfigFactory default is 0, which skips wait_for_ci entirely in
    PostMergeHandler._run_ci_gate). We pass a custom config so the CI gate runs.

    FakeDocker invocations (9 total — the gate passes first attempt):
      1. Initial agent _execute (streaming) — commits code
      2–4. Three post-implementation skill _execute calls — default success
           (diff-sanity, scope-check, test-adequacy;
           plan-compliance is skipped: empty prompt with no plan)
      5. test-adequacy's ``make coverage 0`` probe (run_simple) — default success
      6. Pre-quality review _execute, attempt 1 — default success
      7. Pre-quality run-tool _execute, attempt 1 — default success
      8. make quality-lite (run_simple) — PASSES
      9. Test step, `make test` (run_simple) — PASSES

    CI fail/fix is handled by FakeGitHub.script_ci + FakeLLM.reviewers.fix_ci
    and does NOT consume FakeDocker slots.
    """
    from tests.helpers import ConfigFactory  # noqa: PLC0415

    # max_ci_fix_attempts=1 enables the CI gate (PostMergeHandler._run_ci_gate
    # returns True immediately if max_ci_fix_attempts == 0, skipping wait_for_ci).
    config = ConfigFactory.create(
        repo_root=tmp_path / "repo",
        workspace_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
        max_workers=1,
        max_planners=1,
        max_reviewers=1,
        visual_validation_enabled=False,
        max_ci_fix_attempts=1,
    )
    world = MockWorld(tmp_path, use_real_agent_runner=True, config=config)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])
    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    init_test_worktree(worktree_cwd)

    _ok = [{"type": "result", "success": True, "exit_code": 0}]

    # 1) Initial agent run: commits code
    world.docker.script_run_with_commits(
        events=[{"type": "result", "success": True, "exit_code": 0}],
        commits=[("x.py", "ok")],
        cwd=worktree_cwd,
    )
    # 2–5) Three post-implementation skill _execute calls + the coverage probe
    # (diff-sanity, scope-check, test-adequacy) — default success
    # plan-compliance is skipped: returns empty prompt with no plan → no _execute
    for _ in range(4):
        world.docker.script_run(_ok)
    # 6–7) Pre-quality review loop attempt 1: review + run_tool — both default success
    world.docker.script_run(_ok)  # review pass
    world.docker.script_run(_ok)  # run_tool pass
    # 8–9) make quality-lite, then the test step — both PASS (no quality-fix loop)
    world.docker.script_run(_ok)
    world.docker.script_run(_ok)

    # CI scripted: fail first, pass second.
    # FakeGitHub._pr_counter starts at 10_000; the first PR created is 10_000.
    world.github.script_ci(
        pr_number=10_000,
        results=[(False, "test failed"), (True, "CI passed")],
    )

    result = await world.run_pipeline()

    # The issue should have been merged after fix_ci resolved CI
    assert result.issue(1).merged, (
        f"expected merged=True; outcome={result.issue(1)!r}; "
        f"docker_invocations={len(world.docker.invocations)}"
    )

    # A PR was created and merged
    pr = world.github.pr_for_issue(1)
    assert pr is not None
    assert pr.merged is True

    # 9 FakeDocker invocations: 1 agent + 3 skills + 1 coverage probe
    # + 2 pre-quality + quality-lite + test step
    assert len(world.docker.invocations) >= 9

    # Defense: if PR numbering changes, wait_for_ci returns default success and
    # the scripted fail/pass queue stays full. Assert it was consumed.
    assert pr.number in world.github._ci_scripts
    assert len(world.github._ci_scripts[pr.number]) == 0, (
        "fix_ci loop did not consume the scripted CI queue — wait_for_ci may have "
        "missed the PR entirely (check FakeGitHub._pr_counter initial value)"
    )


async def test_A12_multi_commit_implement(tmp_path) -> None:
    """Real agent produces 3 commits; `git rev-list --count` observes them.

    Uses FakeDocker.script_run_with_multiple_commits to simulate an agent that
    produces N distinct commits in a single run. Each batch is committed
    separately with message `fake-commit-{i}`.
    """
    import subprocess

    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])
    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    init_test_worktree(worktree_cwd)

    world.docker.script_run_with_multiple_commits(
        events=[{"type": "result", "success": True, "exit_code": 0}],
        commit_batches=[
            [("a.py", "step 1")],
            [("b.py", "step 2")],
            [("c.py", "step 3")],
        ],
        cwd=worktree_cwd,
    )

    result = await world.run_pipeline()

    assert result.issue(1).merged, f"expected merged=True; outcome={result.issue(1)}"

    # Verify 3 agent-generated commits on the branch (excludes initial empty commit on main)
    count = subprocess.run(
        ["git", "rev-list", "--count", "origin/main..agent/issue-1"],
        cwd=worktree_cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    observed = int(count.stdout.strip())
    assert observed == 3, f"expected 3 commits on branch; observed {observed}"

    # Verify all 3 files exist
    for filename in ("a.py", "b.py", "c.py"):
        assert (worktree_cwd / filename).exists(), f"missing {filename}"


async def test_A13_zero_diff_fails_without_merge(tmp_path) -> None:
    """Agent claims success but commits nothing → WorkerResult failure, no merge.

    Production ``AgentRunner._verify_result`` runs ``git rev-list --count``
    (on host via FakeSubprocessRunner._HOST_COMMANDS).  Observing 0 commits
    causes ``_verify_result`` to return
    ``LoopResult(passed=False, summary="No commits found on branch")``,
    which propagates to ``WorkerResult(success=False, error="No commits found
    on branch", commits=0)``.

    ``_handle_implementation_result`` then calls ``_is_zero_commit_failure``
    (checks ``not result.success and result.error == "No commits found on
    branch" and result.commits == 0``), which returns True, routing into
    ``_handle_zero_commits`` — marking the issue failed without creating a PR
    or merging.

    The scripted stream uses ``script_run`` (not ``script_run_with_commits``)
    so no real git commit is ever written to the worktree.  The success flag
    in the stream event is irrelevant: ``_verify_result`` fails on the commit
    count gate before the quality check even runs.
    """
    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])
    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    init_test_worktree(worktree_cwd)

    # Agent "succeeds" but writes no commits (plain script_run, not script_run_with_commits)
    world.docker.script_run([{"type": "result", "success": True, "exit_code": 0}])

    result = await world.run_pipeline()

    # Issue must NOT merge — zero commits means _verify_result fails
    assert not result.issue(1).merged, f"expected no merge; outcome={result.issue(1)}"

    # WorkerResult should be present with success=False
    wr = result.issue(1).worker_result
    assert wr is not None, "expected a WorkerResult recording the failure"
    assert wr.success is False, f"expected success=False; got {wr}"


async def test_A13b_null_delivery_diagrams_only_fails_without_merge(tmp_path) -> None:
    """Agent commits ONLY a planner diagram → null-delivery guard, no merge (#9480).

    The planner copies ``.likec4`` context diagrams into the worktree; when the
    implementer produces no code, the auto-commit fallback salvages only those
    diagrams, yielding a commit (so the zero-commit gate passes) whose diff is
    diagrams-only. ``ImplementPhase._handle_implementation_result`` calls the
    null-delivery guard (``_is_null_delivery`` → ``null_delivery.is_null_delivery``
    over ``git diff --name-only``), which routes the run to a failed attempt with
    no PR — preventing a PR that would falsely close the issue on merge.

    Uses ``script_run_with_commits`` to write+commit a single
    ``docs/architecture/*.likec4`` file so ``_verify_result`` observes a commit,
    exercising the real git diff + classifier path end-to-end.
    """
    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])
    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    init_test_worktree(worktree_cwd)

    world.docker.script_run_with_commits(
        events=[{"type": "result", "success": True, "exit_code": 0}],
        commits=[("docs/architecture/change-area.likec4", "// diagram only\n")],
        cwd=worktree_cwd,
    )

    result = await world.run_pipeline()

    assert not result.issue(1).merged, (
        f"diagrams-only delivery must not merge; outcome={result.issue(1)}"
    )
    wr = result.issue(1).worker_result
    assert wr is not None, "expected a WorkerResult recording the failure"
    assert wr.success is False, f"expected success=False; got {wr}"


async def test_A14_three_issues_concurrent_realistic(tmp_path) -> None:
    """Three issues run through real AgentRunner concurrently; all merge.

    Each issue's worktree is isolated — the scripted commits target each
    issue's specific `cwd`. FakeDocker's script FIFO is consumed in real
    invocation order, so the 3 scripted calls can match any of the 3
    issues. The scenario asserts overall pipeline success and worktree
    isolation (each issue's own file is present, others' are not).

    Each issue gets its own bare origin under ``tmp_path / "origins" /
    "issue-{n}.git"`` via ``init_test_worktree(..., origin=...)``. This
    avoids conflicts on the default ``origin.git`` name when multiple
    worktrees share the same parent directory.

    If cross-contamination is observed (one issue gets another's file),
    this scenario would need keyed FakeDocker scripting — a separate fix.
    """
    world = MockWorld(tmp_path, use_real_agent_runner=True)

    for n in (1, 2, 3):
        world.add_issue(n, f"issue {n}", f"body {n}", labels=["hydraflow-ready"])

        wt = tmp_path / "worktrees" / f"issue-{n}"
        # Per-issue bare origin so that multiple repos don't conflict on push.
        origin = tmp_path / "origins" / f"issue-{n}.git"

        init_test_worktree(wt, branch=f"agent/issue-{n}", origin=origin)

        world.docker.script_run_with_commits(
            events=[{"type": "result", "success": True, "exit_code": 0}],
            commits=[(f"file{n}.py", f"content {n}")],
            cwd=wt,
        )

    result = await world.run_pipeline()

    # All 3 issues should merge
    for n in (1, 2, 3):
        outcome = result.issue(n)
        assert outcome.merged, f"issue {n} did not merge: {outcome}"
        assert outcome.worker_result is not None
        assert outcome.worker_result.issue_number == n, (
            f"cross-contamination: issue {n}'s result bound to "
            f"{outcome.worker_result.issue_number}"
        )

    # Exactly 3 PRs, one per issue
    prs = [world.github.pr_for_issue(n) for n in (1, 2, 3)]
    assert all(p is not None and p.merged for p in prs), f"PRs: {prs}"

    # At least 3 docker invocations (expect many more: skills, quality, etc.)
    assert len(world.docker.invocations) >= 3


async def test_A17_authentication_error_halts_pipeline(tmp_path) -> None:
    """AuthenticationError from _execute propagates out of run_pipeline.

    Like CreditExhaustedError, AuthenticationError is in the re-raise
    allowlist in _process_done_tasks at src/phase_utils.py.
    """
    from unittest import mock

    import pytest

    from subprocess_util import AuthenticationError
    from tests.scenarios.helpers.git_worktree_fixture import init_test_worktree

    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])
    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    init_test_worktree(worktree_cwd)

    agent_runner = world.harness.agents

    async def raising_execute(*args, **kwargs):
        raise AuthenticationError("401 unauthorized")

    with (
        mock.patch.object(agent_runner, "_execute", raising_execute),
        pytest.raises(AuthenticationError),
    ):
        await world.run_pipeline()


async def test_A18_rate_limit_heals_mid_pipeline(tmp_path) -> None:
    """Arm rate-limit, let early calls succeed, heal via on_phase hook, complete.

    Scripts `remaining=5` so the first 5 GitHub calls succeed. An `on_phase`
    hook on `"implement"` heals the rate-limit before the implement-phase
    starts its GitHub calls. Pipeline runs to completion.
    """
    from tests.scenarios.helpers.git_worktree_fixture import init_test_worktree

    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])
    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    init_test_worktree(worktree_cwd)

    world.docker.script_run_with_commits(
        events=[{"type": "result", "success": True, "exit_code": 0}],
        commits=[("x.py", "ok")],
        cwd=worktree_cwd,
    )

    # Allow 5 GitHub calls then raise; but heal before it matters
    world.github.set_rate_limit_mode(remaining=5)

    def heal_github() -> None:
        world.github.clear_rate_limit()

    world.on_phase("implement", heal_github)

    result = await world.run_pipeline()

    # Pipeline must complete and merge despite the rate-limit arming
    assert result.issue(1).merged, f"expected merged=True; outcome={result.issue(1)}"


async def test_A16_credit_exhausted_halts_pipeline(tmp_path) -> None:
    """CreditExhaustedError from _execute propagates out of run_pipeline.

    `phase_utils.handle_pool_worker_exception` re-raises CreditExhaustedError
    (with the rest of `exception_classify.FATAL_EXCEPTIONS`) after cancelling
    sibling tasks. Non-fatal exceptions are absorbed and logged at warning.
    """
    from unittest import mock

    from subprocess_util import CreditExhaustedError

    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])
    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    init_test_worktree(worktree_cwd)

    agent_runner = world.harness.agents

    async def raising_execute(*args, **kwargs):
        raise CreditExhaustedError("API credit limit reached", resume_at=None)

    with (
        mock.patch.object(agent_runner, "_execute", raising_execute),
        pytest.raises(CreditExhaustedError),
    ):
        await world.run_pipeline()


async def test_A19_code_scanning_alerts_reach_reviewer(tmp_path) -> None:
    """Scripted code-scanning alerts propagate through review pipeline.

    FakeGitHub.add_alerts(branch=...) seeds alerts for the branch. Matches
    PRPort.fetch_code_scanning_alerts(branch: str) signature — ReviewPhase
    fetches by branch (not PR number) and passes the list to ReviewRunner.review.
    FakeLLM.reviewers records what it received; we assert the alert list reached
    the reviewer unchanged.
    """
    from models import CodeScanningAlert
    from tests.scenarios.helpers.git_worktree_fixture import init_test_worktree

    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])
    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    init_test_worktree(worktree_cwd)

    world.docker.script_run_with_commits(
        events=[{"type": "result", "success": True, "exit_code": 0}],
        commits=[("x.py", "ok")],
        cwd=worktree_cwd,
    )

    alerts = [
        CodeScanningAlert(
            number=1,
            severity="error",
            security_severity="high",
            path="x.py",
            start_line=1,
            rule="py/test",
            message="an alert",
        ),
    ]
    # Production ReviewPhase calls fetch_code_scanning_alerts(pr.branch) — the
    # branch is the key in FakeGitHub._alerts.
    world.github.add_alerts(branch="agent/issue-1", alerts=alerts)

    await world.run_pipeline()

    # Pipeline ran and reviewer saw the alerts
    received = world._llm.alerts_received_by_reviewer(1)
    assert received == alerts, f"reviewer received {received!r}"


async def test_A20_workspace_create_permission_failure(tmp_path) -> None:
    """FakeWorkspace.fail_next_create raises PermissionError; pipeline handles gracefully.

    The PermissionError from workspace creation is swallowed by the implement
    phase's exception handler (non-allowlisted errors are caught and logged).
    The issue therefore does not merge, and run_pipeline returns normally.
    """
    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])

    # No worktree init needed — the failure happens BEFORE workspace creation.
    world._workspace.fail_next_create(kind="permission")

    result = await world.run_pipeline()

    # Pipeline does not crash. Issue fails without merging.
    assert not result.issue(1).merged, f"expected no merge; outcome={result.issue(1)}"

    # Workspace failure must produce a concrete observable signal.
    # Production wraps the PermissionError in a WorkerResult(success=False) via
    # run_with_fatal_guard → the worker_result is set and records the error.
    # Assert the three real-signal arms; the tautological `worker_result is None`
    # arm has been removed — if none of these hold the test must fail loudly.
    outcome = result.issue(1)
    observed_failure = (
        # Worker recorded the failure (PermissionError surfaces as failed WorkerResult)
        (outcome.worker_result is not None and outcome.worker_result.success is False)
        # OR the issue was escalated / reset (HITL or find path)
        or outcome.final_stage in ("hitl", "find")
        # OR a comment was posted about the failure
        or any(
            "permission" in c[1].lower() or "workspace" in c[1].lower()
            for c in world.github._comments
        )
    )
    assert observed_failure, (
        f"workspace failure produced no observable signal — "
        f"outcome={outcome}, comments={world.github._comments}"
    )


async def test_A20b_workspace_create_disk_full(tmp_path) -> None:
    """OSError(ENOSPC) from FakeWorkspace is swallowed gracefully."""
    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])

    world._workspace.fail_next_create(kind="disk_full")

    result = await world.run_pipeline()
    assert not result.issue(1).merged


async def test_A20c_workspace_create_branch_conflict(tmp_path) -> None:
    """RuntimeError ('worktree already exists') from FakeWorkspace is swallowed."""
    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])

    world._workspace.fail_next_create(kind="branch_conflict")

    result = await world.run_pipeline()
    assert not result.issue(1).merged


async def test_A21_state_json_corruption_graceful_fallback(tmp_path) -> None:
    """Corrupt state.json before run; StateTracker falls back to empty state.

    Per src/state/__init__.py, `StateTracker.load` catches `JSONDecodeError`
    and OSError, tries `.bak` files, then falls back to empty `StateData()`.
    Pipeline must still run — a corrupt state file is recoverable.

    PipelineHarness uses `state_file=tmp_path / "state.json"`, so corrupting
    that file BEFORE MockWorld construction exercises the real StateTracker
    fallback path.  The pipeline proceeds with a fresh empty state, and the
    issue is processed normally.
    """
    from tests.scenarios.helpers.git_worktree_fixture import init_test_worktree

    # Corrupt the state file before MockWorld (and therefore StateTracker) is created
    state_file = tmp_path / "state.json"
    state_file.write_text('{"this is": broken json no closing brace')

    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])
    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    init_test_worktree(worktree_cwd)

    world.docker.script_run_with_commits(
        events=[{"type": "result", "success": True, "exit_code": 0}],
        commits=[("x.py", "ok")],
        cwd=worktree_cwd,
    )

    # Pipeline must not raise on startup despite the corrupt state file.
    # StateTracker.load() catches JSONDecodeError and falls back to StateData().
    result = await world.run_pipeline()

    # Verify StateTracker fell back to empty state — _data must be a valid
    # StateData object, not None and not the corrupted JSON string.
    from models import StateData  # noqa: PLC0415

    state_data = world.harness.state._data
    assert state_data is not None, "StateTracker._data is None after corrupt load"
    assert isinstance(state_data, StateData), (
        f"StateTracker._data is not a StateData instance after corrupt load: "
        f"{type(state_data)!r}"
    )

    # The pipeline reached a terminal stage — corruption did not prevent processing.
    outcome = result.issue(1)
    assert outcome.final_stage in ("triage", "plan", "implement", "review", "done"), (
        f"unexpected final_stage={outcome.final_stage!r} after corrupt state recovery"
    )


async def test_A22_wiki_populated_plan_consults_it(tmp_path) -> None:
    """Pre-populated RepoWikiStore is wired to PlanPhase; wiki is accessible.

    NOTE: The realistic-agent path uses FakeLLM for planning (scripted), so
    ``plan_phase._wiki_ingest_plan`` runs with the default FakeLLM plan text
    (``"## Plan\\n\\n1. Do the thing\\n2. Test the thing"``).  That text contains
    no "architecture", "design", "risks", or "testing" sections, so
    ``ingest_from_plan`` extracts 0 entries and writes no additional log entry.
    Therefore ``post_count > pre_count`` would be a false gate on the scripted
    path.

    Instead, this test verifies:
    1. The wiki_store is correctly wired to PlanPhase (_wiki_store attribute is set).
    2. The pre-ingest call wrote a log entry (wiki storage works end-to-end).
    3. The pipeline ran to completion with the wiki in place (no crash from wiki wiring).

    A stricter query-consultation test requires a real LLM planner that reads wiki
    context before generating the plan — that is exercised in integration tests.
    """
    from repo_wiki import RepoWikiStore, WikiEntry
    from tests.scenarios.helpers.git_worktree_fixture import init_test_worktree

    wiki = RepoWikiStore(tmp_path / "wiki")
    # Pre-populate with one patterns entry using the real WikiEntry model
    wiki.ingest(
        "test-org/test-repo",
        entries=[
            WikiEntry(
                title="use async everywhere",
                content="All handlers must be async to avoid blocking the event loop.",
                source_type="plan",
                source_issue=None,
            )
        ],
    )

    world = MockWorld(tmp_path, use_real_agent_runner=True, wiki_store=wiki)
    world.add_issue(1, "add async handler", "body", labels=["hydraflow-ready"])
    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    init_test_worktree(worktree_cwd)

    world.docker.script_run_with_commits(
        events=[{"type": "result", "success": True, "exit_code": 0}],
        commits=[("x.py", "ok")],
        cwd=worktree_cwd,
    )

    # Verify wiki_store is wired to PlanPhase BEFORE running the pipeline
    assert world.harness.plan_phase._wiki_store is wiki, (
        "wiki_store not wired to PlanPhase — PipelineHarness did not pass it through"
    )

    result = await world.run_pipeline()

    # The pre-ingest call above always writes a log entry — verify end-to-end
    # storage works (log file exists and is non-empty).
    log_path = tmp_path / "wiki" / "test-org" / "test-repo" / "log.jsonl"
    assert log_path.exists(), (
        f"wiki log missing at {log_path} — RepoWikiStore layout may have changed"
    )
    assert log_path.read_text().strip(), (
        "wiki log exists but is empty — pre-ingest should have written it"
    )

    # Pipeline completed without crashing despite wiki being wired.
    assert result.issue(1).merged, (
        f"expected merged=True with wiki wired; outcome={result.issue(1)}"
    )


async def test_A23_auth_retry_marker_heals_then_merges(tmp_path) -> None:
    """`authentication_failed` in the agent stream triggers the retryable
    auth path: runner_utils._is_auth_failure raises AuthenticationRetryError,
    base_runner._execute retries up to _AUTH_RETRY_MAX, and the issue merges
    when a later attempt succeeds (#8365).

    Distinct from A17 (AuthenticationError hard-halt via a mocked _execute) —
    this exercises the *real* in-_execute detection of the
    `authentication_failed` stream marker plus the retry loop and heal-to-merge.
    A4 documents that `auth_retry_required` is an unknown event type that the
    StreamParser ignores; the real production trigger is the marker string in
    the raw stream, which is what this scripts.
    """
    from tests.scenarios.helpers.git_worktree_fixture import init_test_worktree

    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])
    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    init_test_worktree(worktree_cwd, branch="agent/issue-1")

    # Attempts 1 and 2: the stream carries the `authentication_failed` marker,
    # so runner_utils raises AuthenticationRetryError and base_runner retries.
    def _auth_fail_stream() -> list[dict[str, object]]:
        return [
            {"type": "error", "subtype": "authentication_failed"},
            {"type": "result", "success": False, "exit_code": 1},
        ]

    world.docker.script_run(_auth_fail_stream())
    world.docker.script_run(_auth_fail_stream())
    # Attempt 3 (the last allowed by _AUTH_RETRY_MAX=3): clean success + commit.
    world.docker.script_run_with_commits(
        events=[{"type": "result", "success": True, "exit_code": 0}],
        commits=[("x.py", "fixed after auth retry")],
        cwd=worktree_cwd,
    )

    result = await world.run_pipeline()

    outcome = result.issue(1)
    assert outcome.merged, (
        f"expected merged after auth-retry heal; outcome={outcome!r}; "
        f"docker_invocations={len(world.docker.invocations)}"
    )
    # Proves the retry loop fired: 2 auth-failed attempts + 1 success ⇒ ≥3
    # implement invocations before any post-implement skill runs.
    assert len(world.docker.invocations) >= 3, (
        f"expected >=3 implement attempts (2 auth-retry + 1 heal); "
        f"got {len(world.docker.invocations)}"
    )


async def test_A24_rate_limit_in_implement_phase_no_special_handling(tmp_path) -> None:
    """GitHub rate-limit fired during the implement phase (the create_pr path)
    — documents that prod has NO bespoke rate-limit handling there (#8366).

    A6/A7 arm the limit before triage, so it fires at the earliest GitHub call
    (triage's find_existing_issue) and the issue never reaches implement. This
    scenario lets triage + plan succeed, then arms `remaining=0` via an
    `on_phase("implement", ...)` hook (the inverse of A18's heal) so the limit
    first bites inside the implement phase — the same phase that owns
    `pr_manager.create_pr`.

    Finding (#8366): there is no create_pr-specific retry/backoff/HITL path.
    The implement phase's GitHub calls (label/PR ops including create_pr) all
    route through `FakeGitHub._maybe_rate_limit`; the resulting `RateLimitError`
    is outside `exception_classify.FATAL_EXCEPTIONS`, so
    `phase_utils.run_refilling_pool` absorbs it as a non-fatal warning (same
    path as A6). Targeting create_pr *exactly* would need a fragile tuned
    `remaining=N` budget — the issue explicitly accepts documenting the
    phase-level finding instead.

    Observable behaviour (asserted so the test fails if handling changes):
    `run_pipeline` returns normally, the issue is not merged, no PR is
    recorded, and the rate-limit was consumed.
    """
    from tests.scenarios.helpers.git_worktree_fixture import init_test_worktree

    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])
    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    init_test_worktree(worktree_cwd, branch="agent/issue-1")

    world.docker.script_run_with_commits(
        events=[{"type": "result", "success": True, "exit_code": 0}],
        commits=[("x.py", "ok")],
        cwd=worktree_cwd,
    )

    # Triage + plan run with no limit; arm remaining=0 as implement starts.
    world.on_phase("implement", lambda: world.github.set_rate_limit_mode(remaining=0))

    result = await world.run_pipeline()

    # No bespoke handling: RateLimitError is pool-absorbed, pipeline returns
    # normally, the issue does not merge, and no PR exists.
    assert not result.issue(1).merged, f"unexpected merge; outcome={result.issue(1)}"
    assert world.github.pr_for_issue(1) is None, "no PR should be created"
    assert world.github._rate_limit_remaining == 0, "rate-limit should be consumed"


async def test_A25_test_adequacy_verifier_second_opinion_on_explicit_ok(
    tmp_path,
) -> None:
    """A25: explicit adequacy OK dispatches the independent verifier (#9546).

    The verifier is gated on the finder's EXPLICIT ``TEST_ADEQUACY_RESULT: OK``
    marker — the no-marker default-pass used by every other scenario in this
    file must stay verifier-free (A0/A10/A11 passing unchanged with the
    verifier default-enabled IS that pin). Here the finder emits the explicit
    marker, so the pipeline grows exactly one loop-visible verifier dispatch.

    FakeDocker FIFO (scripts are consumed by ALL calls in order):

      1. Initial agent _execute (streaming) — commits code
      2. diff-sanity skill _execute — default success (no marker)
      3. scope-check skill _execute — default success
         (plan-compliance is skipped: empty prompt with no plan)
      4. test-adequacy finder _execute — EXPLICIT OK marker via assistant event
      5. ``make coverage 0`` (run_simple via FakeDocker) — exit 0, no
         coverage.xml → coverage delta gracefully preserves the pass
      6. VERIFIER _execute — CONCUR via assistant event  ← the new dispatch
      7–9. pre-quality review / run-tool / implement gate — default success

    The AgentRunner in scenarios builds its own default config
    (``build_real_agent_runner`` → ``ConfigFactory.create()``), so this test
    also proves the kill-switch is default-ON and the verifier model default
    is independent of the finder's: both are read from the invocation argv.
    """
    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])
    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    init_test_worktree(worktree_cwd)

    _ok = [{"type": "result", "success": True, "exit_code": 0}]

    def _text_events(text: str) -> list[dict]:
        return [
            {
                "type": "assistant",
                "message": {"id": "m1", "content": [{"type": "text", "text": text}]},
            },
            {"type": "result", "success": True, "exit_code": 0},
        ]

    # 1) Initial agent run: commits code
    world.docker.script_run_with_commits(
        events=[{"type": "result", "success": True, "exit_code": 0}],
        commits=[("x.py", "ok")],
        cwd=worktree_cwd,
    )
    # 2–3) diff-sanity + scope-check — default success
    world.docker.script_run(_ok)
    world.docker.script_run(_ok)
    # 4) test-adequacy finder — EXPLICIT OK (the verifier trigger)
    world.docker.script_run(
        _text_events("TEST_ADEQUACY_RESULT: OK\nSUMMARY: coverage adequate")
    )
    # 5) make coverage 0 — exit 0, no coverage.xml (graceful preserve)
    world.docker.script_run(_ok)
    # 6) independent verifier — CONCUR keeps the pass
    world.docker.script_run(
        _text_events(
            "TEST_ADEQUACY_VERIFIER_RESULT: CONCUR\nSUMMARY: independently confirmed"
        )
    )
    # 7–9) pre-quality review, run-tool, implement gate — default success
    world.docker.script_run(_ok)
    world.docker.script_run(_ok)
    world.docker.script_run(_ok)

    result = await world.run_pipeline()

    assert result.issue(1).merged, (
        f"expected merged=True; outcome={result.issue(1)!r}; "
        f"docker_invocations={len(world.docker.invocations)}"
    )

    def _model_of(command: list[str]) -> str:
        return command[command.index("--model") + 1]

    # Exactly one verifier dispatch, identified by its prompt in the argv.
    verifier_invs = [
        inv
        for inv in world.docker.invocations
        if any("INDEPENDENT Test Adequacy Verifier" in arg for arg in inv.command)
    ]
    assert len(verifier_invs) == 1, (
        f"expected exactly 1 verifier dispatch, got {len(verifier_invs)}; "
        f"commands={[' '.join(i.command)[:80] for i in world.docker.invocations]}"
    )
    finder_invs = [
        inv
        for inv in world.docker.invocations
        if any("Test Adequacy skill" in arg for arg in inv.command)
    ]
    assert len(finder_invs) == 1
    # Model independence, observed at the dispatch boundary: a shared model
    # would defeat the second opinion.
    assert _model_of(verifier_invs[0].command) != _model_of(finder_invs[0].command)
