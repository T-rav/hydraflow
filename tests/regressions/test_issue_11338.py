"""Regression pin for #11338 — scripted implement seeds' "branch" key was inert.

Root cause: ``FakeLLM._coerce_implement`` forwarded a scripted dict's keys to
``WorkerResultFactory.create`` via ``_filter_kwargs``, but when the dict
*omitted* ``branch`` entirely, the factory fell back to its own hardcoded
default (``branch: str = "agent/issue-42"``) rather than the actual issue
number. That silently mismatched every unscripted branch against the real
pipeline's ``f"agent/issue-{issue.id}"`` convention (``implement_phase.py``'s
``_worker``), and made the sandbox scenario seeds' scripted
``"branch": "hf/issue-N"`` values read as if they were the real branch name
when nothing downstream ever consumes them.

Pin: an omitted ``branch`` key in a scripted implement dict must default to
``f"agent/issue-{issue_number}"`` — the same convention production code uses
— not the factory's issue-agnostic hardcoded default.
"""

from __future__ import annotations

from pathlib import Path

from tests.conftest import TaskFactory


async def test_coerce_implement_defaults_branch_to_agent_issue_number_when_omitted() -> (
    None
):
    from mockworld.fakes.fake_llm import FakeLLM

    llm = FakeLLM()
    llm.script_implement(7, [{"success": True}])

    task = TaskFactory.create(id=7)
    result = await llm.agents.run(task, Path("/tmp"), "some-other-branch")

    assert result.branch == "agent/issue-7"


async def test_coerce_implement_respects_explicit_branch_when_provided() -> None:
    from mockworld.fakes.fake_llm import FakeLLM

    llm = FakeLLM()
    llm.script_implement(7, [{"success": True, "branch": "custom/branch"}])

    task = TaskFactory.create(id=7)
    result = await llm.agents.run(task, Path("/tmp"), "some-other-branch")

    assert result.branch == "custom/branch"
