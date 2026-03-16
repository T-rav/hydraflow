"""Tests for conftest factory None-sentinel defaults."""

from __future__ import annotations

from models import GitHubIssueState
from tests.conftest import IssueFactory, TaskFactory


class TestIssueFactoryNoneSentinels:
    """IssueFactory optional params use None sentinel, not truthy checks."""

    def test_default_labels_applied(self):
        issue = IssueFactory.create()
        assert issue.labels == ["ready"]

    def test_explicit_empty_labels_preserved(self):
        issue = IssueFactory.create(labels=[])
        assert issue.labels == []

    def test_default_comments_applied(self):
        issue = IssueFactory.create()
        assert issue.comments == []

    def test_explicit_empty_comments_preserved(self):
        issue = IssueFactory.create(comments=[])
        assert issue.comments == []

    def test_default_url_generated(self):
        issue = IssueFactory.create(number=99)
        assert str(issue.url) == "https://github.com/test-org/test-repo/issues/99"

    def test_explicit_empty_url_preserved(self):
        issue = IssueFactory.create(url="")
        assert str(issue.url) == ""

    def test_explicit_url_used(self):
        issue = IssueFactory.create(url="https://example.com/issues/1")
        assert str(issue.url) == "https://example.com/issues/1"

    def test_default_state_is_open(self):
        issue = IssueFactory.create()
        assert issue.state == GitHubIssueState.OPEN

    def test_explicit_state_closed(self):
        issue = IssueFactory.create(state=GitHubIssueState.CLOSED)
        assert issue.state == GitHubIssueState.CLOSED

    def test_explicit_state_open(self):
        issue = IssueFactory.create(state=GitHubIssueState.OPEN)
        assert issue.state == GitHubIssueState.OPEN


class TestTaskFactoryNoneSentinels:
    """TaskFactory optional params use None sentinel, not truthy checks."""

    def test_default_tags_applied(self):
        task = TaskFactory.create()
        assert task.tags == ["ready"]

    def test_explicit_empty_tags_preserved(self):
        task = TaskFactory.create(tags=[])
        assert task.tags == []

    def test_default_comments_applied(self):
        task = TaskFactory.create()
        assert task.comments == []

    def test_explicit_empty_comments_preserved(self):
        task = TaskFactory.create(comments=[])
        assert task.comments == []

    def test_default_source_url_generated(self):
        task = TaskFactory.create(id=77)
        assert str(task.source_url) == "https://github.com/test-org/test-repo/issues/77"

    def test_explicit_empty_source_url_preserved(self):
        task = TaskFactory.create(source_url="")
        assert str(task.source_url) == ""
