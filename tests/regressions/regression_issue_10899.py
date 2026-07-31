"""Regression for #10899: FakeGitHub's two workflow identifiers stay distinct.

The real adapter passes the workflow **file** name in the REST path
(``actions/workflows/{file}/runs``) for ``list_runs_for_workflow``, while
``list_workflow_runs`` returns each run's **display** name (``.name``).
FakeGitHub stored a single ``workflow`` field for both, so no seed value was
faithful on both sides — a file name in the display slot passed in MockWorld and
failed live, and vice versa. ``add_workflow_run`` now takes a separate
``workflow_file``; these tests pin that each method keys on the right one.
"""

from __future__ import annotations

import pytest

from mockworld.fakes.fake_github import FakeGitHub


class TestWorkflowRunKeyFidelity:
    @staticmethod
    def _seed(fake: FakeGitHub) -> None:
        fake.add_workflow_run(
            1,
            workflow="CI",  # display name (.name)
            workflow_file="ci.yml",  # file the real adapter queries by
            conclusion="success",
        )

    @pytest.mark.asyncio
    async def test_list_runs_for_workflow_keys_on_file_not_display_name(self) -> None:
        fake = FakeGitHub()
        self._seed(fake)

        assert [r["id"] for r in await fake.list_runs_for_workflow("ci.yml")] == [1]
        # The display name must NOT match — that is the pre-fix conflation.
        assert await fake.list_runs_for_workflow("CI") == []

    @pytest.mark.asyncio
    async def test_list_workflow_runs_projects_display_name(self) -> None:
        fake = FakeGitHub()
        self._seed(fake)

        listed = await fake.list_workflow_runs()

        assert [r["workflow"] for r in listed] == ["CI"]
