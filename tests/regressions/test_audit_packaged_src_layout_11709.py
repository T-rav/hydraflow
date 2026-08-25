"""Regression: the audit must assess a ``src/<pkg>/`` repo, not miss at the probe.

#11709. ``scripts/hydraflow_audit/`` resolved every source module as a flat
literal ``ctx.root / "src" / "<name>.py"``, while
``src/onboarding/kernel_writer.py`` stamps the packaged layout
(``src/{pkg}/__init__.py`` + ``pythonpath = ["src"]``). Twenty-four sites
across seven files disagreed with the writer, so a freshly stamped repo failed
its own building code: every affected check returned ``FAIL: src/<name>.py
missing`` and the thing it exists to assess was never assessed.

HydraFlow itself is flat-src, so **every one of these checks passed here and
was blind on every stamped repo** — green where it is unnecessary, silent where
it is needed. Nothing in this repo's own audit run can catch that, which is why
the gate has to be a synthetic packaged fixture.

What these tests pin, and why they are shaped this way
------------------------------------------------------
The exit code alone cannot tell ``FAIL: src/ports.py missing`` (exited at the
probe) from ``FAIL: ports exist but define no Protocol`` (actually assessed).
So every case here asserts on the **reason**:

* the *conformant* fixture must reach ``PASS`` — impossible for a flat literal,
  which never sees ``src/<pkg>/ports.py`` at all;
* the *non-conformant* fixture must fail for the **content** reason and must
  not mention a missing path.

Revert the resolver and both halves redden. Refs #11673 (the class: a file path
used as a proxy for a module identity), Refs #6855 (a gate that went missing).
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
from scripts.hydraflow_audit import context, registry  # noqa: F401
from scripts.hydraflow_audit.checks import (  # noqa: F401
    p1_docs,
    p2_architecture,
    p3_testing,
    p6_agents,
    p7_observability,
    p8_superpowers,
    p9_persistence,
    p10_tdd,
)
from scripts.hydraflow_audit.checks._helpers import finding
from scripts.hydraflow_audit.models import CheckContext, Finding, Status

from false_close import UI_TEST_RE

PKG = "memoiq"

#: What ``kernel_writer._pyproject`` stamps, trimmed to the parts that matter
#: for package discovery.
_PYPROJECT = f"""[project]
name = "{PKG}"
version = "0.1.0"

[project.scripts]
{PKG} = "{PKG}.cli:main"

[tool.pytest.ini_options]
pythonpath = ["src"]
"""

# --- fixture repos --------------------------------------------------------

_PORTS_CONFORMANT = """
from typing import Protocol


class VCSPort(Protocol):
    def push(self) -> None: ...


class ObservabilityPort(Protocol):
    def emit(self) -> None: ...
"""

_PORTS_NO_PROTOCOL = """
class VCSPort:
    def push(self) -> None: ...
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

_CONFIG_NO_DATA_ROOT = """
from pydantic import BaseModel, Field


class Settings(BaseModel):
    ready_label: str = Field(default="ready")
"""

_ORCHESTRATOR_CONFORMANT = """
import asyncio


async def main() -> None:
    await asyncio.gather(loop_a(), loop_b())
"""

_ORCHESTRATOR_NO_CONCURRENCY = """
async def main() -> None:
    await loop_a()
    await loop_b()
"""

#: A conformant packaged repo: every module the converted checks probe, at
#: ``src/<pkg>/…`` and nowhere else.
_CONFORMANT: dict[str, str] = {
    "pyproject.toml": _PYPROJECT,
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

#: The same packaged repo with each probed module PRESENT but NOT conformant.
#: This is the half that proves the check reached its real assessment: a flat
#: literal cannot tell this repo from the one above — it sees neither.
_PRESENT_BUT_NONCONFORMANT: dict[str, str] = {
    **_CONFORMANT,
    f"src/{PKG}/ports.py": _PORTS_NO_PROTOCOL,
    f"src/{PKG}/orchestrator.py": _ORCHESTRATOR_NO_CONCURRENCY,
    f"src/{PKG}/config.py": _CONFIG_NO_DATA_ROOT,
    f"src/{PKG}/base_background_loop.py": "class SomethingElse:\n    pass\n",
}


def _materialize(root: Path, spec: dict[str, str]) -> Path:
    for rel, body in spec.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return root


@pytest.fixture
def packaged_repo(tmp_path: Path) -> Path:
    """A conformant repo in the layout ``kernel_writer`` stamps."""
    return _materialize(tmp_path, _CONFORMANT)


@pytest.fixture
def packaged_repo_noncompliant(tmp_path: Path) -> Path:
    """Same layout; the probed modules exist but violate their checks."""
    return _materialize(tmp_path, _PRESENT_BUT_NONCONFORMANT)


#: The exact shape of a "exited at the path probe" message: a resolved source
#: path followed immediately by ``missing``, optionally with a trailing
#: ``— <clause>``. Deliberately narrower than a bare ``"missing" in message``:
#: real content verdicts say ``... — concurrent loop shape missing`` and
#: ``src/<pkg>/repo_wiki.py missing operations: ...``, and neither is a probe
#: exit. A crude substring test would flag those and get relaxed into
#: uselessness the first time it did.
_PROBE_EXIT_RE = re.compile(r"src/\S+ missing(?: —[^:]*)?$")


def _run(check_id: str, root: Path) -> Finding:
    fn = registry.get(check_id)
    assert fn is not None, f"{check_id} is not registered"
    return fn(context.build(root))


# --- shape detection ------------------------------------------------------


def test_packaged_repo_is_detected_as_an_orchestration_repo(
    packaged_repo: Path,
) -> None:
    """P6 is NA for a non-orchestration repo — a blind probe makes every
    stamped repo look like one, silently retiring the whole principle."""
    ctx = context.build(packaged_repo)

    assert ctx.src_packages == (PKG,)
    assert ctx.is_orchestration_repo is True


def test_packaged_ui_directory_is_detected(packaged_repo: Path) -> None:
    assert context.build(packaged_repo).has_ui is True


# --- every converted check reaches PASS on a conformant packaged repo -----

#: ``(check_id, expected_status)`` for the conformant fixture. Anything other
#: than the expected status here means the check never saw ``src/<pkg>/``.
_CONFORMANT_EXPECTATIONS = [
    ("P2.2", Status.PASS),  # ports module has a Protocol
    ("P2.2a", Status.PASS),  # two Protocols cover two boundaries
    ("P2.5", Status.PASS),  # composition root found
    ("P2.8", Status.PASS),  # domain types carry behaviour
    ("P3.3", Status.PASS),  # scenario fakes exist
    ("P3.13", Status.PASS),  # clock fake exists
    ("P3.14", Status.PASS),  # fakes do not inherit Mock
    ("P6.1", Status.PASS),  # orchestrator gathers loops
    ("P6.2", Status.PASS),  # labels centralised in config
    ("P6.3", Status.PASS),  # BaseBackgroundLoop defined
    ("P6.5", Status.PASS),  # atomic label swap helper
    ("P7.3b", Status.PASS),  # wiki store operations
    ("P7.3c", Status.PASS),  # runner injects the wiki
    ("P7.7", Status.PASS),  # observability behind a port
    ("P8.6", Status.PASS),  # trace collector
    ("P9.1", Status.PASS),  # data_root config field
]


@pytest.mark.parametrize(("check_id", "expected"), _CONFORMANT_EXPECTATIONS)
def test_check_evaluates_a_packaged_repo(
    packaged_repo: Path, check_id: str, expected: Status
) -> None:
    finding = _run(check_id, packaged_repo)

    assert finding.status is expected, (
        f"{check_id} returned {finding.status.value} ({finding.message!r}) on a "
        f"conformant src/{PKG}/ repo. A flat src/<name>.py probe cannot see "
        "this layout at all (#11709)."
    )


@pytest.mark.parametrize(("check_id", "_expected"), _CONFORMANT_EXPECTATIONS)
def test_no_check_reports_a_missing_path_on_a_packaged_repo(
    packaged_repo: Path, check_id: str, _expected: Status
) -> None:
    """The exact #11709 symptom, asserted on the reason rather than the verdict."""
    message = _run(check_id, packaged_repo).message

    assert not _PROBE_EXIT_RE.search(message), (
        f"{check_id} exited at a path probe on a packaged repo: {message!r}"
    )


# --- present-but-non-conformant: the check reached its real assessment ----

#: ``(check_id, expected_status, reason_fragment)``. The fragment is the
#: *content* verdict — it can only be produced by a check that opened the file
#: at ``src/<pkg>/…``. A flat literal reports a missing path instead.
_CONTENT_VERDICTS = [
    ("P2.2", Status.FAIL, "defines no Protocol classes"),
    ("P2.2a", Status.WARN, "only 0 Protocol"),
    ("P6.1", Status.FAIL, "no asyncio.gather"),
    ("P6.2", Status.FAIL, "not centralised"),
    ("P6.3", Status.FAIL, "BaseBackgroundLoop class not found"),
    ("P7.7", Status.WARN, "no ObservabilityPort"),
    ("P9.1", Status.FAIL, "no `data_root` field"),
]


@pytest.mark.parametrize(
    ("check_id", "expected", "fragment"),
    _CONTENT_VERDICTS,
)
def test_check_fails_for_the_content_reason_not_a_missing_path(
    packaged_repo_noncompliant: Path,
    check_id: str,
    expected: Status,
    fragment: str,
) -> None:
    finding = _run(check_id, packaged_repo_noncompliant)

    assert finding.status is expected
    assert fragment in finding.message, (
        f"{check_id} should have assessed the file's CONTENT; it said "
        f"{finding.message!r}. 'FAIL: <path> missing' and 'FAIL: assessed and "
        "non-conformant' are indistinguishable from the exit code alone."
    )
    assert not _PROBE_EXIT_RE.search(finding.message)


# --- messages name the path actually probed -------------------------------


def test_absent_module_message_names_the_packaged_path(tmp_path: Path) -> None:
    """A stamped repo missing ``ports.py`` must be told about ITS path."""
    _materialize(
        tmp_path,
        {"pyproject.toml": _PYPROJECT, f"src/{PKG}/__init__.py": ""},
    )

    finding = _run("P2.2", tmp_path)

    assert finding.status is Status.FAIL
    assert finding.message == f"src/{PKG}/ports.py missing"


# --- the flat layout is unchanged -----------------------------------------

_FLAT: dict[str, str] = {
    rel.replace(f"src/{PKG}/", "src/"): body
    for rel, body in _CONFORMANT.items()
    if rel != f"src/{PKG}/__init__.py"
}


@pytest.mark.parametrize(("check_id", "expected"), _CONFORMANT_EXPECTATIONS)
def test_flat_layout_verdicts_are_unchanged(
    tmp_path: Path, check_id: str, expected: Status
) -> None:
    """The safety property of a 24-site conversion: flat repos resolve as before."""
    root = _materialize(tmp_path, _FLAT)

    assert CheckContext(root=root).src_packages == ()
    assert _run(check_id, root).status is expected


# --- guard the guard ------------------------------------------------------

_PROBE_EXIT_MESSAGES = [
    pytest.param("src/memoiq/ports.py missing", id="bare"),
    pytest.param(
        "src/memoiq/base_background_loop.py missing — BaseBackgroundLoop not defined",
        id="with-trailing-clause",
    ),
    pytest.param("src/ports.py missing", id="flat-spelling"),
]

_CONTENT_VERDICT_MESSAGES = [
    pytest.param(
        "src/memoiq/orchestrator.py has no asyncio.gather / TaskGroup — "
        "concurrent loop shape missing",
        id="trailing-word-missing",
    ),
    pytest.param(
        "src/memoiq/repo_wiki.py missing operations: query, lint",
        id="missing-operations",
    ),
    pytest.param("src/memoiq/ports.py defines no Protocol classes", id="no-protocol"),
]


@pytest.mark.parametrize("message", _PROBE_EXIT_MESSAGES)
def test_probe_exit_detector_catches_a_probe_exit(message: str) -> None:
    assert _PROBE_EXIT_RE.search(message)


@pytest.mark.parametrize("message", _CONTENT_VERDICT_MESSAGES)
def test_probe_exit_detector_ignores_real_content_verdicts(message: str) -> None:
    assert not _PROBE_EXIT_RE.search(message)


def test_the_packaged_fixture_actually_hides_the_flat_paths() -> None:
    """Guard the fixture: a stray flat module would make every case vacuous."""
    flat_modules = [
        rel
        for rel in _CONFORMANT
        if rel.startswith("src/") and not rel.startswith(f"src/{PKG}/")
    ]

    assert flat_modules == []


# --- per-literal coverage for the multi-candidate probes ------------------
#
# Several converted checks probe a LIST of alternative modules and stop at the
# first hit. A fixture holding the first alternative proves only that literal;
# the siblings would stay unconverted and nothing would redden. Each case below
# supplies exactly ONE alternative, so every converted literal has a test that
# fails when its own conversion is reverted.

_SINGLE_CANDIDATE_CASES = [
    # P2.5 composition root — src/<pkg>/{service_registry,composition_root,container}.py
    pytest.param(
        "P2.5", "service_registry.py", "REGISTRY = {}\n", id="P2.5-service_registry"
    ),
    pytest.param(
        "P2.5", "composition_root.py", "ROOT = {}\n", id="P2.5-composition_root"
    ),
    pytest.param("P2.5", "container.py", "CONTAINER = {}\n", id="P2.5-container"),
    # P6.5 atomic label swap — pr_manager / pr_manager_labels / label_manager / labels
    pytest.param(
        "P6.5",
        "pr_manager.py",
        "def swap_pipeline_labels() -> None: ...\n",
        id="P6.5-pr_manager",
    ),
    pytest.param(
        "P6.5",
        "pr_manager_labels.py",
        "def swap_pipeline_labels() -> None: ...\n",
        id="P6.5-pr_manager_labels",
    ),
    pytest.param(
        "P6.5",
        "label_manager.py",
        "def swap_labels() -> None: ...\n",
        id="P6.5-label_manager",
    ),
    pytest.param(
        "P6.5", "labels.py", "def atomic_label_swap() -> None: ...\n", id="P6.5-labels"
    ),
    # P7.3c wiki injection — base_runner / runner
    pytest.param(
        "P7.3c",
        "base_runner.py",
        "def build():\n    _inject_repo_wiki()\n",
        id="P7.3c-base_runner",
    ),
    pytest.param(
        "P7.3c",
        "runner.py",
        "def build():\n    _inject_repo_wiki()\n",
        id="P7.3c-runner",
    ),
    # P8.6 trace writer — trace_collector / tracing
    pytest.param(
        "P8.6",
        "trace_collector.py",
        "import subprocess  # writes the trace\n",
        id="P8.6-trace_collector",
    ),
    pytest.param(
        "P8.6",
        "tracing.py",
        "import subprocess  # writes the trace\n",
        id="P8.6-tracing",
    ),
    # P2.8 domain sample — models.py and domain/ are two independent literals
    pytest.param(
        "P2.8",
        "models.py",
        "class Order:\n    def total(self) -> int:\n        return 0\n",
        id="P2.8-models",
    ),
    pytest.param(
        "P2.8",
        "domain/order.py",
        "class Order:\n    def total(self) -> int:\n        return 0\n",
        id="P2.8-domain-dir",
    ),
]


@pytest.mark.parametrize(("check_id", "rel", "body"), _SINGLE_CANDIDATE_CASES)
def test_each_alternative_candidate_resolves_on_its_own(
    tmp_path: Path, check_id: str, rel: str, body: str
) -> None:
    root = _materialize(
        tmp_path,
        {
            "pyproject.toml": _PYPROJECT,
            f"src/{PKG}/__init__.py": "",
            # P6 checks self-mark NA off shape detection, which is itself one
            # of the converted probes; without a marker the case would pass on
            # an NA that proves nothing.
            f"src/{PKG}/orchestrator.py": "import asyncio\n",
            f"src/{PKG}/{rel}": body,
        },
    )

    finding = _run(check_id, root)

    assert finding.status is Status.PASS, (
        f"{check_id} did not find src/{PKG}/{rel} — that literal is still flat "
        f"({finding.message!r})."
    )


# --- context.py: each shape-detection literal, on its own -----------------

_ORCHESTRATION_MARKERS = [
    pytest.param("orchestrator.py", id="orchestrator"),
    pytest.param("base_background_loop.py", id="base_background_loop"),
]


@pytest.mark.parametrize("rel", _ORCHESTRATION_MARKERS)
def test_each_orchestration_marker_is_seen_on_its_own(tmp_path: Path, rel: str) -> None:
    """``_detect_orchestration`` ORs two probes; a fixture with both hides one."""
    root = _materialize(
        tmp_path,
        {
            "pyproject.toml": _PYPROJECT,
            f"src/{PKG}/__init__.py": "",
            f"src/{PKG}/{rel}": "x = 1\n",
        },
    )

    assert context.build(root).is_orchestration_repo is True


def test_packaged_ui_is_seen_without_a_repo_root_ui_directory(
    tmp_path: Path,
) -> None:
    """``_detect_ui`` ORs ``<root>/ui`` with the source-tree probe."""
    root = _materialize(
        tmp_path,
        {
            "pyproject.toml": _PYPROJECT,
            f"src/{PKG}/__init__.py": "",
            f"src/{PKG}/ui/app.tsx": "export const App = () => null;\n",
        },
    )

    assert not (root / "ui").exists()
    assert context.build(root).has_ui is True


# --- the FAIL/NA messages name the packaged path too ----------------------
#
# Some converted sites only run on the *unhappy* path — they build the message
# that says where the audit looked. A packaged fixture that only exercises PASS
# leaves them unproven: reverting them to a flat literal changes nothing any
# test can see, and the next reader is told to create `src/mockworld/fakes/` in
# a repo whose source root is `src/<pkg>/`. Per-site mutation caught these two
# as vacuous; these cases are what made them red.

_EMPTY_PACKAGED_REPO = {
    "pyproject.toml": _PYPROJECT,
    f"src/{PKG}/__init__.py": "",
}


def test_missing_fakes_message_names_the_packaged_directory(tmp_path: Path) -> None:
    root = _materialize(tmp_path, _EMPTY_PACKAGED_REPO)

    finding = _run("P3.3", root)

    assert finding.status is Status.FAIL
    assert f"src/{PKG}/mockworld/fakes/" in finding.message
    assert "src/mockworld/fakes/" not in finding.message


def test_missing_clock_fake_message_names_the_packaged_directory(
    tmp_path: Path,
) -> None:
    root = _materialize(tmp_path, _EMPTY_PACKAGED_REPO)

    finding = _run("P3.13", root)

    assert finding.status is Status.FAIL
    assert f"src/{PKG}/mockworld/fakes/" in finding.message
    assert "src/mockworld/fakes/" not in finding.message


def test_no_domain_sample_message_names_the_packaged_paths(tmp_path: Path) -> None:
    root = _materialize(tmp_path, _EMPTY_PACKAGED_REPO)

    finding = _run("P2.8", root)

    assert finding.status is Status.NA
    assert f"src/{PKG}/models.py" in finding.message
    assert f"src/{PKG}/domain/" in finding.message


# --- P10.6: the UI prefix is a STRING, and it was flat too ----------------
#
# The one converted site that is not a Path expression. P10.6 classifies
# git-diff paths against a `src/ui/` string prefix, and `false_close.UI_TEST_RE`
# anchors on the same literal. On a packaged repo a UI-only fix's paths all
# start with `src/<pkg>/ui/`, so `ui_only` was False, the UI-test escape hatch
# never opened, and P10.6 fell through to WARN — which is NOT in
# `runner._NON_BLOCKING_WARN_CHECKS`, so it failed the audit gate outright.
# A blind Path probe returns a wrong verdict; this one blocked the PR.


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        },
    )


def _ui_fix_pr(root: Path, files: dict[str, str]) -> None:
    """A packaged repo whose branch carries one UI-only ``fix(ui): …`` commit."""
    _materialize(root, _EMPTY_PACKAGED_REPO)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "chore: base")
    _git(root, "checkout", "-q", "-b", "fix/ui")
    _materialize(root, files)
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "fix(ui): cap the dots")


def test_packaged_ui_only_fix_with_a_ui_test_delta_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ui_fix_pr(
        tmp_path,
        {
            f"src/{PKG}/ui/src/StreamView.jsx": "cap\n",
            f"src/{PKG}/ui/src/__tests__/StreamView.test.jsx": "t\n",
        },
    )
    monkeypatch.setenv("HYDRAFLOW_AUDIT_PR_BASE", "main")

    result = _run("P10.6", tmp_path)

    assert result.status is Status.PASS, (
        f"P10.6 blocked a packaged UI-only fix: {result.message!r}"
    )
    assert "UI" in (result.message or "")


def test_packaged_ui_only_fix_without_a_ui_test_still_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gate must still bite — the fix widens the layout, not the rule."""
    _ui_fix_pr(tmp_path, {f"src/{PKG}/ui/src/StreamView.jsx": "cap\n"})
    monkeypatch.setenv("HYDRAFLOW_AUDIT_PR_BASE", "main")

    result = _run("P10.6", tmp_path)

    assert result.status is Status.WARN
    assert f"src/{PKG}/ui/" in (result.message or "")


def test_flat_ui_only_fix_still_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Widening the prefix must not stop the flat layout from matching."""
    _materialize(tmp_path, {"src/app.py": "x = 1\n"})
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "chore: base")
    _git(tmp_path, "checkout", "-q", "-b", "fix/ui")
    _materialize(
        tmp_path,
        {
            "src/ui/src/StreamView.jsx": "cap\n",
            "src/ui/src/__tests__/StreamView.test.jsx": "t\n",
        },
    )
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "fix(ui): cap the dots")
    monkeypatch.setenv("HYDRAFLOW_AUDIT_PR_BASE", "main")

    result = _run("P10.6", tmp_path)

    assert result.status is Status.PASS
    assert "UI" in (result.message or "")


_UI_TEST_PATHS = [
    pytest.param("src/ui/src/__tests__/View.jsx", id="flat-tests-dir"),
    pytest.param("src/ui/src/View.test.tsx", id="flat-dot-test"),
    pytest.param(f"src/{PKG}/ui/src/__tests__/View.jsx", id="packaged-tests-dir"),
    pytest.param(f"src/{PKG}/ui/src/View.test.tsx", id="packaged-dot-test"),
]


@pytest.mark.parametrize("path", _UI_TEST_PATHS)
def test_ui_test_regex_matches_both_layouts(path: str) -> None:
    assert UI_TEST_RE.match(path)


_NOT_UI_TEST_PATHS = [
    pytest.param("src/ui/src/View.jsx", id="ui-product-not-a-test"),
    pytest.param(f"src/{PKG}/ui/src/View.jsx", id="packaged-ui-product"),
    pytest.param("docs/ui/__tests__/View.jsx", id="not-under-src"),
    pytest.param(f"src/{PKG}/deep/ui/src/View.test.tsx", id="two-segments-deep"),
]


@pytest.mark.parametrize("path", _NOT_UI_TEST_PATHS)
def test_ui_test_regex_stays_anchored(path: str) -> None:
    """Widened by exactly one optional package segment — not turned into `.*`."""
    assert not UI_TEST_RE.match(path)


# --- multi-candidate FAIL messages name the paths they probed -------------
#
# The flat-wins precedence is argued on "a wrong answer is never a SILENT one —
# every check reports the path it actually probed." The multi-candidate probes
# used to list bare filenames ("tried service_registry.py, composition_root.py,
# container.py"), which is exactly the information a stamped repo cannot act on
# and makes that argument untrue where it matters most.

_MULTI_CANDIDATE_PROBES = [
    pytest.param(
        "P2.5",
        ("service_registry.py", "composition_root.py", "container.py"),
        id="P2.5-composition-root",
    ),
    pytest.param(
        "P6.5",
        ("pr_manager.py", "pr_manager_labels.py", "label_manager.py", "labels.py"),
        id="P6.5-label-swap",
    ),
    pytest.param("P7.3c", ("base_runner.py", "runner.py"), id="P7.3c-runner"),
    pytest.param("P8.6", ("trace_collector.py", "tracing.py"), id="P8.6-trace"),
]


@pytest.mark.parametrize(("check_id", "modules"), _MULTI_CANDIDATE_PROBES)
def test_multi_candidate_failure_names_every_packaged_path(
    tmp_path: Path, check_id: str, modules: tuple[str, ...]
) -> None:
    root = _materialize(
        tmp_path,
        {
            **_EMPTY_PACKAGED_REPO,
            # P6 self-marks NA off shape detection unless a marker is present.
            f"src/{PKG}/orchestrator.py": "import asyncio\n",
        },
    )

    message = _run(check_id, root).message

    for module in modules:
        assert f"src/{PKG}/{module}" in message, (
            f"{check_id} listed a bare filename instead of the path it probed: "
            f"{message!r}. A stamped repo cannot act on {module!r} alone."
        )


@pytest.mark.parametrize(("check_id", "modules"), _MULTI_CANDIDATE_PROBES)
def test_multi_candidate_success_names_the_packaged_path(
    tmp_path: Path, check_id: str, modules: tuple[str, ...]
) -> None:
    """The PASS message identifies which candidate matched, by full path."""
    bodies = {
        "P2.5": "REGISTRY = {}\n",
        "P6.5": "def swap_pipeline_labels() -> None: ...\n",
        "P7.3c": "def build():\n    _inject_repo_wiki()\n",
        "P8.6": "import subprocess  # writes the trace\n",
    }
    root = _materialize(
        tmp_path,
        {
            **_EMPTY_PACKAGED_REPO,
            f"src/{PKG}/orchestrator.py": "import asyncio\n",
            f"src/{PKG}/{modules[0]}": bodies[check_id],
        },
    )

    finding = _run(check_id, root)

    assert finding.status is Status.PASS
    if check_id != "P7.3c":  # P7.3c's PASS message carries no path
        assert f"src/{PKG}/{modules[0]}" in finding.message


def test_scan_root_reaches_into_the_package(tmp_path: Path) -> None:
    """``ctx.src_root()`` is layout-agnostic — rglob from src/ sees src/<pkg>/**.

    P9.2 passing while its sibling P9.1 failed is how #11709 announced itself;
    this pins the property that made P9.2 immune, so a future "fix" cannot
    narrow the scan roots to the package and reintroduce the asymmetry.
    """
    root = _materialize(
        tmp_path,
        {
            **_EMPTY_PACKAGED_REPO,
            f"src/{PKG}/settings.py": 'import os\nX = os.environ["APP_DATA_ROOT"]\n',
        },
    )

    finding = _run("P9.2", root)

    assert finding.status is Status.PASS
    assert "settings.py" in finding.message


# --- the backstop: EVERY registered check, not a hand-listed 16 -----------
#
# The static ratchet (tests/architecture/test_audit_src_layout_ratchet.py) gates
# on the LITERAL `src`, on the premise that every spelling of the hazard must
# contain it. That premise is false, and no literal rule can repair it: the
# vocabulary itself builds flat paths on request.
#
#     probe = ctx.src_root() / f"{name}.py"          # no literal `src`
#     probe = ctx.root / SOURCE_DIR_NAME / "x.py"    # no literal `src`
#
# Both resolve to `src/x.py` on a packaged repo — #11709 verbatim — and both
# sail past a spelling gate. `src_root()` is documented as a RECURSIVE scan root
# (rglob from it reaches `src/<pkg>/**`), but nothing stops someone appending a
# filename, and that is the natural next keystroke.
#
# Enumerating spellings failed five times; enumerating misuses of the sanctioned
# calls would fail the same way. The layer that closes it in one assertion,
# independent of spelling, is behavioural: run the WHOLE registry against a
# packaged fixture and assert nothing exits at a path probe. A check added
# tomorrow is covered without anyone remembering to list it — which is the
# difference between this and `_CONFORMANT_EXPECTATIONS` above.


def _probe_exit_findings(root: Path) -> dict[str, str]:
    """``{check_id: message}`` for every check that exits at a path probe."""
    ctx = context.build(root)
    offenders: dict[str, str] = {}
    for check_id, fn in sorted(registry.all_registered().items()):
        message = fn(ctx).message or ""
        if _PROBE_EXIT_RE.search(message):
            offenders[check_id] = message
    return offenders


def test_no_registered_check_exits_at_a_path_probe(packaged_repo: Path) -> None:
    """The spelling-independent backstop for the whole #11709 class."""
    offenders = _probe_exit_findings(packaged_repo)

    assert offenders == {}, (
        f"These checks never assessed a packaged repo, they missed at the path "
        f"probe: {offenders}. Resolve modules with ctx.src_module(...) / "
        "ctx.src_dir(...) — ctx.src_root() is a RECURSIVE scan root, and "
        "appending a filename to it rebuilds the #11709 bug (#11709)."
    )


def test_the_sweep_catches_a_flat_probe_the_literal_gate_cannot_see(
    packaged_repo: Path,
) -> None:
    """Guard the guard, with the exact evasion the static ratchet is blind to.

    Plants a check that builds a flat probe out of the vocabulary itself, so
    the source text contains no ``src`` literal at all. If this sweep ever
    stops catching it, the class has no remaining gate.
    """
    snapshot = registry._snapshot_for_tests()
    try:

        @registry.register("ZZ.1")
        def _planted(ctx: CheckContext) -> Finding:
            probe = ctx.src_root() / "ports.py"  # the Rank-1 evasion
            if not probe.exists():
                return finding("ZZ.1", Status.FAIL, f"{ctx.rel(probe)} missing")
            return finding("ZZ.1", Status.PASS)

        offenders = _probe_exit_findings(packaged_repo)
    finally:
        registry._restore_for_tests(snapshot)

    assert "ZZ.1" in offenders, (
        "the registry sweep no longer catches a flat probe built from "
        f"ctx.src_root() — got {offenders}"
    )
    assert (
        offenders["ZZ.1"] == f"src/{PKG}/ports.py missing"
        or offenders["ZZ.1"] == "src/ports.py missing"
    )


def test_the_sweep_covers_the_whole_registry(packaged_repo: Path) -> None:
    """Guard the guard: an empty registry would pass the sweep vacuously."""
    context.build(packaged_repo)

    assert len(registry.all_registered()) >= 90, (
        f"only {len(registry.all_registered())} checks registered — the sweep "
        "above would pass with almost nothing to run"
    )
