"""Conformance tests — each fake must satisfy its Port protocol.

Uses runtime_checkable isinstance checks. If a fake drifts from its port,
this test flags it immediately.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from events import EventBus
from mockworld.fakes.fake_clock import FakeClock
from mockworld.fakes.fake_docker import FakeDocker
from mockworld.fakes.fake_fs import FakeFS
from mockworld.fakes.fake_git import FakeGit
from mockworld.fakes.fake_github import FakeGitHub
from mockworld.fakes.fake_http import FakeHTTP
from mockworld.fakes.fake_issue_fetcher import FakeIssueFetcher
from mockworld.fakes.fake_issue_store import FakeIssueStore
from mockworld.fakes.fake_llm import FakeLLM
from mockworld.fakes.fake_sentry import FakeSentry
from mockworld.fakes.fake_workspace import FakeWorkspace
from tests.scenarios.ports import (
    ClockPort,
    DockerPort,
    FSPort,
    GitPort,
    HTTPPort,
    IssueFetcherPort,
    IssueStorePort,
    LLMPort,
    PRPort,
    SentryPort,
    WorkspacePort,
)


def _fake_clock() -> FakeClock:
    import time

    return FakeClock(start=time.time())


def _fake_github() -> FakeGitHub:
    return FakeGitHub()


def _fake_issue_fetcher() -> FakeIssueFetcher:
    return FakeIssueFetcher(_fake_github())


def _fake_issue_store() -> FakeIssueStore:
    return FakeIssueStore(_fake_github(), EventBus())


def _fake_workspace() -> FakeWorkspace:
    return FakeWorkspace(Path("/tmp/mockworld-runtime-conformance"))


@pytest.mark.parametrize(
    "factory,port",
    [
        (_fake_clock, ClockPort),
        (FakeDocker, DockerPort),
        (FakeFS, FSPort),
        (FakeGit, GitPort),
        (_fake_github, PRPort),
        (FakeHTTP, HTTPPort),
        (_fake_issue_fetcher, IssueFetcherPort),
        (_fake_issue_store, IssueStorePort),
        (FakeLLM, LLMPort),
        (FakeSentry, SentryPort),
        (_fake_workspace, WorkspacePort),
    ],
    ids=[
        "FakeClock-ClockPort",
        "FakeDocker-DockerPort",
        "FakeFS-FSPort",
        "FakeGit-GitPort",
        "FakeGitHub-PRPort",
        "FakeHTTP-HTTPPort",
        "FakeIssueFetcher-IssueFetcherPort",
        "FakeIssueStore-IssueStorePort",
        "FakeLLM-LLMPort",
        "FakeSentry-SentryPort",
        "FakeWorkspace-WorkspacePort",
    ],
)
def test_fake_satisfies_declared_port(factory, port) -> None:
    assert isinstance(factory(), port)


def test_fake_subprocess_runner_satisfies_subprocess_runner() -> None:
    from execution import SubprocessRunner
    from mockworld.fakes.fake_docker import FakeDocker
    from mockworld.fakes.fake_subprocess_runner import FakeSubprocessRunner

    assert isinstance(FakeSubprocessRunner(FakeDocker()), SubprocessRunner)


def test_real_agent_runner_constructs_via_factory(tmp_path: Path) -> None:
    """Boot smoke — if this fails, AgentRunner API drifted from scenarios."""
    from mockworld.fakes.fake_docker import FakeDocker
    from tests.scenarios.helpers.agent_runner_factory import build_real_agent_runner

    runner = build_real_agent_runner(
        docker=FakeDocker(),
        event_bus=EventBus(),
        tmp_path=tmp_path,
    )
    # We only need the methods that implement_phase actually calls
    assert hasattr(runner, "run")
    assert hasattr(runner, "set_tracing_context")
    assert hasattr(runner, "clear_tracing_context")
