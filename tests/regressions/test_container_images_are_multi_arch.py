"""Every published container image must carry a native arm64 manifest.

All three images were `platforms: linux/amd64`, so an Apple Silicon operator
ran the factory under emulation — or, for the base, could not pull it at all
(`no matching manifest for linux/arm64/v8`). That is the failure this pins.

Two properties, and the second is the one that rots quietly:

1. **Both arches are built.** A workflow that drops one still publishes, just
   single-arch, under a name everyone believes is multi-arch.
2. **Each arch is built on its OWN native runner**, never QEMU. Emulated builds
   of a ~2 GB image with NodeSource, a uv resolve and a Python venv are slow
   enough that someone eventually deletes the arm64 leg to get CI back — so
   "multi-arch via QEMU" decays to "amd64 only" on a timescale of weeks.

The workflow list is DERIVED — any workflow invoking `docker/build-push-action`
is in scope — so a fourth image cannot be added without meeting the rule.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

_WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"

#: Native runner labels, by architecture. `ubuntu-24.04-arm` is free for public
#: repositories, which is what makes native arm64 viable here at all.
_NATIVE_RUNNERS = {"linux/amd64": "ubuntu-latest", "linux/arm64": "ubuntu-24.04-arm"}


def _image_workflows() -> list[Path]:
    """Workflows that build container images — derived, never listed.

    A hardcoded list is the failure mode this whole rule is about: the next
    image gets added, nobody remembers the list, and it ships amd64-only.
    """
    found = [
        path
        for path in sorted(_WORKFLOWS.glob("*.yml"))
        if "docker/build-push-action" in path.read_text(encoding="utf-8")
    ]
    assert found, (
        "no image-building workflows found — the derivation has stopped seeing "
        "its subject, so every assertion below would pass vacuously"
    )
    return found


def _doc(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _platforms_in(job: dict[str, Any]) -> set[str]:
    """Platforms a job builds, resolved through its matrix."""
    include = (job.get("strategy") or {}).get("matrix", {}).get("include") or []
    return {entry["platform"] for entry in include if "platform" in entry}


@pytest.mark.parametrize("workflow", _image_workflows(), ids=lambda p: p.stem)
def test_every_building_job_covers_both_architectures(workflow: Path) -> None:
    """PER JOB, not unioned across the workflow.

    The first version of this test took the union of platforms over every job,
    which meant dropping arm64 from the BUILD job still passed because the PUSH
    job declared it — an image published for both arches but verified for one.
    Mutation-testing caught it; the union read as coverage it did not have.
    """
    jobs_with_matrix = {
        name: job
        for name, job in _doc(workflow)["jobs"].items()
        if _platforms_in(job)
    }
    assert jobs_with_matrix, (
        f"{workflow.name} has no arch matrix at all — it builds a single "
        "architecture, whichever the runner happens to be"
    )

    for name, job in jobs_with_matrix.items():
        missing = set(_NATIVE_RUNNERS) - _platforms_in(job)
        assert not missing, (
            f"{workflow.name}:{name} does not cover {sorted(missing)}. Every "
            "job that builds must build both — a job that builds one arch and "
            "a sibling that builds the other means neither is fully verified."
        )


@pytest.mark.parametrize("workflow", _image_workflows(), ids=lambda p: p.stem)
def test_each_architecture_builds_on_its_own_native_runner(workflow: Path) -> None:
    """Native, not emulated. This is the property that decays if unpinned."""
    for name, job in _doc(workflow)["jobs"].items():
        include = (job.get("strategy") or {}).get("matrix", {}).get("include") or []
        for entry in include:
            platform, runner = entry.get("platform"), entry.get("runner")
            if platform not in _NATIVE_RUNNERS:
                continue
            assert runner == _NATIVE_RUNNERS[platform], (
                f"{workflow.name}:{name} builds {platform} on {runner!r}. "
                f"Expected the native runner {_NATIVE_RUNNERS[platform]!r} — "
                "an emulated build of these images is slow enough that the arm64 "
                "leg gets deleted to unblock CI."
            )


@pytest.mark.parametrize("workflow", _image_workflows(), ids=lambda p: p.stem)
def test_qemu_is_not_used(workflow: Path) -> None:
    """Guard-the-guard: QEMU would satisfy 'builds both arches' while being the
    thing this rule exists to avoid."""
    text = workflow.read_text(encoding="utf-8")

    assert "setup-qemu-action" not in text, (
        f"{workflow.name} sets up QEMU — cross-building these images emulated "
        "is the slow path the native matrix replaced."
    )


@pytest.mark.parametrize("workflow", _image_workflows(), ids=lambda p: p.stem)
def test_a_partial_manifest_is_refused(workflow: Path) -> None:
    """Publishing one digest as a manifest list is worse than not publishing.

    Without this the merge job would happily assemble a single-arch manifest
    when one arch's push failed — and it would look exactly like success.
    """
    doc = _doc(workflow)
    merge = next(
        (j for name, j in doc["jobs"].items() if "merge" in name.lower()), None
    )
    assert merge is not None, f"{workflow.name} has no manifest-merge job"

    runs = " ".join((step.get("run") or "") for step in merge["steps"])
    assert "refusing to publish a partial manifest" in runs, (
        f"{workflow.name}'s merge job does not refuse a partial manifest"
    )
    assert '"architecture":"arm64"' in runs, (
        f"{workflow.name}'s merge job does not verify arm64 reached the registry"
    )
