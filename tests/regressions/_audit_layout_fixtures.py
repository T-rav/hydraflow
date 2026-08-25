"""The one synthetic repo the audit's src-layout gates run against, in both layouts.

``scripts/hydraflow_audit`` must read two ``src/`` layouts (#11709): flat
``src/ports.py`` (HydraFlow itself) and packaged ``src/<pkg>/ports.py`` (what
``src/onboarding/kernel_writer.py`` stamps). The gates that hold that property
need *the same repo* expressed both ways, so a verdict difference can only come
from the layout.

Why this is a module and not a copy in each test file
-----------------------------------------------------
:data:`FLAT` is *derived* from :data:`CONFORMANT` by a comprehension, not
hand-written beside it. Two hand-maintained dicts would drift the moment
someone added a module to one — and a differential comparing two trees that are
no longer the same repo is worse than no differential at all: it reports
disagreements nobody caused, gets exemptions bolted on, and stops meaning
anything. One spec, one mechanical transform, one vocabulary (#11673's shape,
applied to the fixture instead of to the code under test).

Consumers:

* ``test_audit_packaged_src_layout_11709.py`` — per-check assertions that a
  packaged repo reaches its real verdict rather than exiting at a path probe.
* ``test_audit_layout_verdict_differential_11725.py`` — the registry-wide
  flat-vs-packaged status differential.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from scripts.hydraflow_audit import context, registry

__all__ = [
    "CONFORMANT",
    "EMPTY_PACKAGED",
    "FLAT",
    "PKG",
    "PROBE_EXIT_RE",
    "PYPROJECT",
    "flat_rel",
    "git",
    "materialize",
    "probe_exit_findings",
    "ui_fix_branch",
]

PKG = "memoiq"

#: What ``kernel_writer._pyproject`` stamps, trimmed to the parts that matter
#: for package discovery.
PYPROJECT = f"""[project]
name = "{PKG}"
version = "0.1.0"

[project.scripts]
{PKG} = "{PKG}.cli:main"

[tool.pytest.ini_options]
pythonpath = ["src"]
"""

_PORTS_CONFORMANT = """
from typing import Protocol


class VCSPort(Protocol):
    def push(self) -> None: ...


class ObservabilityPort(Protocol):
    def emit(self) -> None: ...
"""

_CONFIG_CONFORMANT = """
from pathlib import Path

from pydantic import BaseModel, Field


class Settings(BaseModel):
    data_root: Path = Field(default=Path(".data"))
    ready_label: str = Field(default="ready")
    building_label: str = Field(default="building")
    review_label: str = Field(default="review")
    done_label: str = Field(default="done")
"""

_ORCHESTRATOR_CONFORMANT = """
import asyncio


async def main() -> None:
    await asyncio.gather(loop_a(), loop_b())
"""

#: A conformant packaged repo: every module the converted checks probe, at
#: ``src/<pkg>/…`` and nowhere else.
CONFORMANT: dict[str, str] = {
    "pyproject.toml": PYPROJECT,
    f"src/{PKG}/__init__.py": "",
    f"src/{PKG}/ports.py": _PORTS_CONFORMANT,
    f"src/{PKG}/service_registry.py": "REGISTRY = {}\n",
    f"src/{PKG}/models.py": (
        "class Order:\n    def total(self) -> int:\n        return 0\n"
    ),
    f"src/{PKG}/domain/order_policy.py": (
        "class OrderPolicy:\n    def apply(self) -> None: ...\n"
    ),
    f"src/{PKG}/orchestrator.py": _ORCHESTRATOR_CONFORMANT,
    f"src/{PKG}/config.py": _CONFIG_CONFORMANT,
    f"src/{PKG}/base_background_loop.py": (
        "class BaseBackgroundLoop:\n    async def run(self) -> None: ...\n"
    ),
    f"src/{PKG}/pr_manager.py": (
        "class PRManager:\n    def swap_pipeline_labels(self) -> None: ...\n"
    ),
    f"src/{PKG}/repo_wiki.py": (
        "class RepoWiki:\n"
        "    def ingest(self) -> None: ...\n"
        "    def query(self) -> None: ...\n"
        "    def lint(self) -> None: ...\n"
    ),
    f"src/{PKG}/base_runner.py": (
        "class BaseRunner:\n"
        "    def build(self) -> None:\n"
        "        self._inject_repo_wiki()\n"
    ),
    f"src/{PKG}/trace_collector.py": (
        "import subprocess\n\n\ndef collect() -> None:\n"
        "    subprocess.run(['git', 'status'], check=False)  # writes the trace\n"
    ),
    f"src/{PKG}/mockworld/fakes/fake_clock.py": (
        "class FakeClock:\n    def now(self) -> int:\n        return 0\n"
    ),
    f"src/{PKG}/mockworld/fakes/fake_vcs.py": (
        "class FakeVCS:\n    def push(self) -> None: ...\n"
    ),
    f"src/{PKG}/mockworld/fakes/fake_wiki.py": (
        "class FakeWiki:\n    def ingest(self) -> None: ...\n"
    ),
    f"src/{PKG}/ui/app.tsx": "export const App = () => null;\n",
}

#: A packaged repo with nothing but its layout — for probe-message assertions.
EMPTY_PACKAGED: dict[str, str] = {
    "pyproject.toml": PYPROJECT,
    f"src/{PKG}/__init__.py": "",
}


def flat_rel(rel: str) -> str:
    """The flat spelling of a packaged repo-relative path."""
    return rel.replace(f"src/{PKG}/", "src/", 1)


#: :data:`CONFORMANT` with the package segment removed — the SAME repo, flat.
#: ``__init__.py`` is dropped because a flat ``src/`` has no root package; that
#: is the only difference beyond the path spelling.
FLAT: dict[str, str] = {
    flat_rel(rel): body
    for rel, body in CONFORMANT.items()
    if rel != f"src/{PKG}/__init__.py"
}


def materialize(root: Path, spec: dict[str, str]) -> Path:
    for rel, body in spec.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return root


#: A frozen identity and clock, so two runs of the same fixture differ in
#: nothing a git-reading check could see.
_GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


def git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        env={**os.environ, **_GIT_ENV},
    )


def ui_fix_branch(root: Path, ui_prefix: str, *, with_test: bool = True) -> Path:
    """Commit the tree, then branch a UI-only ``fix(ui): …`` on top of it.

    The git-dependent checks — P10.6 above all, the only one whose layout
    blindness *blocks* a PR rather than merely misreporting it — are NA on a
    tree with no repository. Without this they sit outside every gate built on
    these fixtures, which is exactly how the flat ``UI_TEST_RE`` survived
    (#11725).

    *ui_prefix* is the repo-relative UI directory for this layout: ``src/ui``
    flat, ``src/<pkg>/ui`` packaged.
    """
    git(root, "init", "-q", "-b", "main")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "chore: base")
    git(root, "checkout", "-q", "-b", "fix/ui")
    delta = {f"{ui_prefix}/src/StreamView.jsx": "cap\n"}
    if with_test:
        delta[f"{ui_prefix}/src/__tests__/StreamView.test.jsx"] = "t\n"
    materialize(root, delta)
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "fix(ui): cap the dots")
    return root


#: The exact shape of an "exited at the path probe" message: a resolved source
#: path followed immediately by ``missing``, optionally with a trailing
#: ``— <clause>``. Deliberately narrower than a bare ``"missing" in message``:
#: real content verdicts say ``... — concurrent loop shape missing`` and
#: ``src/<pkg>/repo_wiki.py missing operations: ...``, and neither is a probe
#: exit. A crude substring test would flag those and get relaxed into
#: uselessness the first time it did.
#:
#: This narrowness is also the registry sweep's ceiling, which is why the
#: differential exists beside it: a flat path that degrades a check into a
#: *wrong verdict* rather than a missing-path exit produces no message this can
#: match (#11725).
PROBE_EXIT_RE = re.compile(r"src/\S+ missing(?: —[^:]*)?$")


def probe_exit_findings(root: Path) -> dict[str, str]:
    """``{check_id: message}`` for every check that exits at a path probe."""
    ctx = context.build(root)
    offenders: dict[str, str] = {}
    for check_id, fn in sorted(registry.all_registered().items()):
        message = fn(ctx).message or ""
        if PROBE_EXIT_RE.search(message):
            offenders[check_id] = message
    return offenders
