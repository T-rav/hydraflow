"""The factory image must be built by the PRs that change it.

`build-agent-image.yml` and `build-agent-base-image.yml` both watch `main`
only. Copying that for the factory image gave it a trigger narrower than its
subject: PRs target `staging` (ADR-0042), so the PR that *introduces* an image
change would never build it, never run its smoke test, and the image would
first be exercised after it had already merged and been promoted.

That is #11730's shape — a gate whose trigger scope is narrower than its
subject scope cannot see its subject — and it was caught on the PR that would
have been its own first victim.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "build-factory-image.yml"

#: Both protected branches (ADR-0042). A change reaches `main` only via an RC
#: promotion, so watching `main` alone means never seeing the PR that made it.
_PROTECTED = ("main", "staging")


def _triggers() -> dict:
    """The workflow's `on:` block.

    PyYAML resolves the bare key ``on`` to the boolean ``True`` (YAML 1.1),
    which is why this is not simply ``doc["on"]`` — reading it wrong yields a
    KeyError rather than a wrong answer, but only if you look for both.
    """
    doc = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    on = doc.get(True, doc.get("on"))
    assert on, "workflow has no `on:` block — the trigger scan has no subject"
    return on


@pytest.mark.parametrize("branch", _PROTECTED)
def test_the_image_builds_for_prs_into_every_protected_branch(branch: str) -> None:
    """A PR that changes the image must build it, on whichever branch it targets."""
    branches = _triggers()["pull_request"]["branches"]

    assert branch in branches, (
        f"PRs into {branch!r} do not build the factory image (watched: {branches}). "
        "A change to the image would merge without its smoke test ever running."
    )


@pytest.mark.parametrize("branch", _PROTECTED)
def test_pushes_to_every_protected_branch_build_the_image(branch: str) -> None:
    branches = _triggers()["push"]["branches"]

    assert branch in branches, (
        f"pushes to {branch!r} do not build the factory image (watched: {branches})"
    )


def test_publishing_is_still_restricted_to_main() -> None:
    """Widening the BUILD trigger must not widen the PUBLISH trigger.

    Guard-the-guard: without this, satisfying the tests above by making the
    push job unconditional would look like a fix and would start publishing
    `:latest` from staging.
    """
    doc = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    push_job = doc["jobs"]["push"]

    assert push_job.get("if") == "github.ref == 'refs/heads/main'", (
        "the publish job is no longer pinned to main — a staging build would "
        f"push :latest. Guard is: {push_job.get('if')!r}"
    )


def test_the_smoke_test_actually_runs_in_the_build_job() -> None:
    """A build that assembles layers proves nothing about whether it runs.

    Without this, deleting the smoke-test step leaves every trigger assertion
    above still green while the image ships unverified.
    """
    doc = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    steps = doc["jobs"]["build"]["steps"]
    runs = " ".join((s.get("run") or "") for s in steps)

    assert "docker-factory-smoke-test.sh" in runs, (
        "the build job no longer runs the smoke test — the image would be "
        "published on the strength of its layers assembling"
    )
