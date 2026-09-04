"""The chain gate at the merge seam (ADR-0149 P4).

Report-only is the property under test as much as the reporting is: a gate
wired into the merge path must never be able to stop a merge, and must
never raise into it.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from change_chain import ChainArtifact, chain_dir, digest, render_plan
from change_chain_gate import ChainFinding
from change_chain_recorder import record_chain
from change_chain_report import (
    COMMENT_HEADING,
    changed_files_from_diff,
    format_findings,
    report_chain_findings,
)
from models import Task
from tests.helpers import ConfigFactory

_DIFF = """diff --git a/src/a.py b/src/a.py
--- a/src/a.py
+++ b/src/a.py
@@ -1 +1 @@
-old
+new
diff --git a/src/b.py b/src/b.py
--- a/src/b.py
+++ b/src/b.py
@@ -1 +1 @@
-old
+new
"""


@pytest.fixture
def config():
    return ConfigFactory.create()


@pytest.fixture
def prs():
    port = MagicMock()
    port.get_pr_diff = AsyncMock(return_value=_DIFF)
    port.post_comment = AsyncMock()
    return port


def _anchor(config, plan: str = "touch src/a.py and src/b.py"):
    return record_chain(config, Task(id=7, title="t", body="b"), plan, "s", None)


def _materialise(config, record) -> None:
    """Put the anchored bodies where the gate looks for them."""
    directory = chain_dir(config.repo_root, 7)
    directory.mkdir(parents=True, exist_ok=True)
    for artifact, body in record.rendered.items():
        (directory / f"{artifact.value}.md").write_text(body, encoding="utf-8")


def test_changed_files_are_read_from_the_post_image_side():
    assert changed_files_from_diff(_DIFF) == ("src/a.py", "src/b.py")


def test_a_pure_deletion_contributes_no_path():
    diff = "--- a/gone.py\n+++ /dev/null\n"

    assert changed_files_from_diff(diff) == ()


def test_an_empty_diff_yields_no_paths():
    assert changed_files_from_diff("") == ()


@pytest.mark.asyncio
async def test_a_matching_chain_reports_nothing(config, prs):
    _materialise(config, _anchor(config))

    findings = await report_chain_findings(
        config=config, prs=prs, pr_number=99, issue_number=7
    )

    assert findings == ()


@pytest.mark.asyncio
async def test_a_clean_chain_posts_no_comment(config, prs):
    _materialise(config, _anchor(config))

    await report_chain_findings(config=config, prs=prs, pr_number=99, issue_number=7)

    prs.post_comment.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_tampered_plan_is_reported(config, prs):
    record = _anchor(config)
    _materialise(config, record)
    (chain_dir(config.repo_root, 7) / "plan.md").write_text("forged", encoding="utf-8")

    findings = await report_chain_findings(
        config=config, prs=prs, pr_number=99, issue_number=7
    )

    assert [f.code for f in findings] == ["chain-digest-mismatch"]


@pytest.mark.asyncio
async def test_a_finding_posts_one_comment_on_the_pr(config, prs):
    record = _anchor(config)
    _materialise(config, record)
    (chain_dir(config.repo_root, 7) / "plan.md").write_text("forged", encoding="utf-8")

    await report_chain_findings(config=config, prs=prs, pr_number=99, issue_number=7)

    prs.post_comment.assert_awaited_once()
    assert prs.post_comment.await_args.args[0] == 99


@pytest.mark.asyncio
async def test_an_unanchored_change_is_reported(config, prs):
    findings = await report_chain_findings(
        config=config, prs=prs, pr_number=99, issue_number=7
    )

    assert [f.code for f in findings] == ["chain-absent"]


@pytest.mark.asyncio
async def test_the_kill_switch_stops_the_gate_entirely(prs):
    config = ConfigFactory.create().model_copy(update={"change_chain_enabled": False})

    findings = await report_chain_findings(
        config=config, prs=prs, pr_number=99, issue_number=7
    )

    assert findings == ()
    prs.get_pr_diff.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_port_failure_does_not_raise_into_the_merge_path(config):
    port = MagicMock()
    port.get_pr_diff = AsyncMock(side_effect=RuntimeError("gh exploded"))
    port.post_comment = AsyncMock()

    findings = await report_chain_findings(
        config=config, prs=port, pr_number=99, issue_number=7
    )

    assert findings == ()


@pytest.mark.asyncio
async def test_a_comment_failure_does_not_raise_into_the_merge_path(config):
    record = _anchor(config)
    _materialise(config, record)
    (chain_dir(config.repo_root, 7) / "plan.md").write_text("forged", encoding="utf-8")
    port = MagicMock()
    port.get_pr_diff = AsyncMock(return_value=_DIFF)
    port.post_comment = AsyncMock(side_effect=RuntimeError("gh exploded"))

    findings = await report_chain_findings(
        config=config, prs=port, pr_number=99, issue_number=7
    )

    assert [f.code for f in findings] == ["chain-digest-mismatch"]


def test_the_comment_names_the_gate_as_report_only():
    body = format_findings(7, (ChainFinding("chain-absent", "no record"),))

    assert COMMENT_HEADING in body
    assert "does not block a merge" in body


def test_the_comment_lists_every_finding():
    body = format_findings(
        7,
        (
            ChainFinding("chain-absent", "first detail"),
            ChainFinding("chain-scope-departure", "second detail"),
        ),
    )

    assert "first detail" in body
    assert "second detail" in body


@pytest.mark.asyncio
async def test_the_digest_the_gate_checks_is_the_anchored_one(config, prs):
    """Guards the scrub-era regression: anchored digest must match the file."""
    record = _anchor(config)
    _materialise(config, record)

    landed = (chain_dir(config.repo_root, 7) / "plan.md").read_text(encoding="utf-8")

    assert digest(landed) == record.digests[ChainArtifact.PLAN]
    assert render_plan(7, "touch src/a.py and src/b.py", "s") == landed
