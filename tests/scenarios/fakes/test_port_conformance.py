"""Conformance tests — each fake must satisfy its Port protocol.

Uses runtime_checkable isinstance checks. If a fake drifts from its port,
this test flags it immediately.
"""

from __future__ import annotations

from tests.scenarios.fakes.fake_clock import FakeClock
from tests.scenarios.fakes.fake_github import FakeGitHub
from tests.scenarios.fakes.fake_hindsight import FakeHindsight
from tests.scenarios.fakes.fake_llm import FakeLLM
from tests.scenarios.fakes.fake_sentry import FakeSentry
from tests.scenarios.ports import (
    ClockPort,
    HindsightPort,
    LLMPort,
    PRPort,
    SentryPort,
)


def test_fake_github_satisfies_pr_port() -> None:
    assert isinstance(FakeGitHub(), PRPort)


def test_fake_llm_satisfies_llm_port() -> None:
    assert isinstance(FakeLLM(), LLMPort)


def test_fake_hindsight_satisfies_hindsight_port() -> None:
    assert isinstance(FakeHindsight(), HindsightPort)


def test_fake_sentry_satisfies_sentry_port() -> None:
    assert isinstance(FakeSentry(), SentryPort)


def test_fake_clock_satisfies_clock_port() -> None:
    import time

    assert isinstance(FakeClock(start=time.time()), ClockPort)
