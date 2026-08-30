"""Tests for P2 (Architecture) check functions."""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.hydraflow_audit import registry  # noqa: F401
from scripts.hydraflow_audit.checks import p2_architecture  # noqa: F401
from scripts.hydraflow_audit.models import CheckContext, Status


def _ctx(root: Path) -> CheckContext:
    return CheckContext(root=root)


def _run(check_id: str, ctx: CheckContext):
    fn = registry.get(check_id)
    assert fn is not None
    return fn(ctx)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# --- P2.1 ----------------------------------------------------------------


def test_src_dir_check(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    assert _run("P2.1", _ctx(tmp_path)).status is Status.PASS


# --- P2.2 and P2.2a ------------------------------------------------------


_PORTS_WITH_TWO_PROTOCOLS = """
from typing import Protocol

class VCSPort(Protocol):
    def push(self) -> None: ...

class WorkspacePort(Protocol):
    def create(self) -> None: ...
"""

_PORTS_WITH_ONE_PROTOCOL = """
from typing import Protocol

class VCSPort(Protocol):
    def push(self) -> None: ...
"""

_PORTS_WITH_NO_PROTOCOLS = """
class NotAPort:
    pass
"""


def test_ports_with_two_protocols_passes(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "ports.py", _PORTS_WITH_TWO_PROTOCOLS)
    assert _run("P2.2", _ctx(tmp_path)).status is Status.PASS
    assert _run("P2.2a", _ctx(tmp_path)).status is Status.PASS


def test_ports_with_one_protocol_warns_on_coverage(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "ports.py", _PORTS_WITH_ONE_PROTOCOL)
    assert _run("P2.2", _ctx(tmp_path)).status is Status.PASS
    assert _run("P2.2a", _ctx(tmp_path)).status is Status.WARN


def test_ports_without_protocols_fails(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "ports.py", _PORTS_WITH_NO_PROTOCOLS)
    assert _run("P2.2", _ctx(tmp_path)).status is Status.FAIL


def test_missing_ports_file_fails(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    assert _run("P2.2", _ctx(tmp_path)).status is Status.FAIL


# --- P2.7 domain purity --------------------------------------------------
#
# The tests these replace fabricated a `scripts/check_layer_imports.py` in
# tmp_path and asserted P2.3/P2.4/P2.6/P2.7 went PASS/FAIL against it. They
# were green for four months while the real repo had no such script and all
# four checks reported NA — the subject existed only inside the tests. These
# exercise the real scan instead.


def test_domain_purity_passes_on_stdlib_and_declarative_imports(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "src" / "models.py",
        "from dataclasses import dataclass\nfrom pydantic import BaseModel\n",
    )
    result = _run("P2.7", _ctx(tmp_path))
    assert result.status is Status.PASS


def test_domain_purity_fails_on_third_party_adapter_sdk(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "models.py", "import docker\n")
    result = _run("P2.7", _ctx(tmp_path))
    assert result.status is Status.FAIL
    assert "docker" in result.message


def test_domain_purity_fails_on_first_party_infrastructure_module(
    tmp_path: Path,
) -> None:
    """A first-party import is judged by naming convention, not by a layer map."""
    _write(tmp_path / "src" / "models.py", "from github_runner import run\n")
    _write(tmp_path / "src" / "github_runner.py", "def run(): ...\n")
    result = _run("P2.7", _ctx(tmp_path))
    assert result.status is Status.FAIL
    assert "github_runner" in result.message


def test_domain_purity_allows_plain_first_party_imports(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "models.py", "from value_objects import Slug\n")
    _write(tmp_path / "src" / "value_objects.py", "Slug = str\n")
    assert _run("P2.7", _ctx(tmp_path)).status is Status.PASS


def test_domain_purity_is_na_only_when_there_is_no_domain_layer(
    tmp_path: Path,
) -> None:
    """The one NA path P2.7 has left — and it is registered as justified."""
    (tmp_path / "src").mkdir()
    result = _run("P2.7", _ctx(tmp_path))
    assert result.status is Status.NA
    assert "declares no domain layer" in result.message


def test_domain_purity_scans_the_domain_package_too(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "domain" / "order.py", "import httpx\n")
    result = _run("P2.7", _ctx(tmp_path))
    assert result.status is Status.FAIL
    assert "httpx" in result.message


def test_domain_purity_flags_infrastructure_reached_across_packages(
    tmp_path: Path,
) -> None:
    """`from ..x import y` leaves the domain's own package — level 1 does not."""
    _write(tmp_path / "src" / "domain" / "order.py", "from ..github_runner import R\n")
    result = _run("P2.7", _ctx(tmp_path))
    assert result.status is Status.FAIL
    assert "github_runner" in result.message


def test_domain_purity_allows_same_package_relative_imports(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "domain" / "order.py", "from . import sibling\n")
    assert _run("P2.7", _ctx(tmp_path)).status is Status.PASS


def test_domain_purity_allows_non_infrastructure_sibling_packages(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "src" / "domain" / "order.py", "from ..value_objects import S\n")
    assert _run("P2.7", _ctx(tmp_path)).status is Status.PASS


@pytest.mark.parametrize("retired", ["P2.3", "P2.4", "P2.6"])
def test_retired_layer_check_ids_are_gone(retired: str) -> None:
    """P2.3/P2.4/P2.6 were retired with their ADR rows (#8383 deleted the subject).

    If a row comes back without an implementation the runner reports
    NOT_IMPLEMENTED, so this asserts the *code* side stays retired; the ADR
    side is asserted by the audit's own row/registry drift check.
    """
    assert registry.get(retired) is None


# --- P2.5 composition root -----------------------------------------------


@pytest.mark.parametrize(
    "filename",
    ["service_registry.py", "composition_root.py", "container.py"],
)
def test_composition_root_detection(filename: str, tmp_path: Path) -> None:
    _write(tmp_path / "src" / filename, "registry = {}")
    assert _run("P2.5", _ctx(tmp_path)).status is Status.PASS


def test_composition_root_missing_fails(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    assert _run("P2.5", _ctx(tmp_path)).status is Status.FAIL


# --- P2.8 anaemic domain -------------------------------------------------


_ANAEMIC_MODELS = """
class Issue:
    def __init__(self, id: int, title: str) -> None:
        self.id = id
        self.title = title

class Task:
    def __init__(self, name: str) -> None:
        self.name = name
"""

_RICH_MODELS = """
class Issue:
    def __init__(self, id: int, title: str) -> None:
        self.id = id
        self.title = title
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def reopen(self) -> None:
        self.closed = False

class Task:
    def __init__(self, name: str) -> None:
        self.name = name

    def run(self) -> None:
        pass
"""


def test_anaemic_domain_warns(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "models.py", _ANAEMIC_MODELS)
    assert _run("P2.8", _ctx(tmp_path)).status is Status.WARN


def test_rich_domain_passes(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "models.py", _RICH_MODELS)
    assert _run("P2.8", _ctx(tmp_path)).status is Status.PASS


def test_no_domain_sample_is_na(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    assert _run("P2.8", _ctx(tmp_path)).status is Status.NA


# --- P2.9 ubiquitous language --------------------------------------------


def test_ubiquitous_language_passes_when_terms_overlap(tmp_path: Path) -> None:
    """CLAUDE.md ToC terms appear in the wiki's architecture topic page."""
    _write(
        tmp_path / "CLAUDE.md",
        "Key concepts: TaskRunner coordinates the pipeline. IssueTracker, LabelMachine, and PhaseGuard round it out.\n",
    )
    _write(
        tmp_path / "docs" / "wiki" / "architecture.md",
        "Core types include TaskRunner, IssueTracker, LabelMachine, PhaseGuard.\n",
    )
    assert _run("P2.9", _ctx(tmp_path)).status is Status.PASS


def test_ubiquitous_language_warns_on_divergence(tmp_path: Path) -> None:
    """CLAUDE.md names types the wiki never explains."""
    _write(
        tmp_path / "CLAUDE.md",
        "Key concepts: AlphaType, BetaType, GammaType, DeltaType.\n",
    )
    _write(
        tmp_path / "docs" / "wiki" / "architecture.md",
        "Some unrelated text.\n",
    )
    assert _run("P2.9", _ctx(tmp_path)).status is Status.WARN


def test_ubiquitous_language_sees_leading_acronym_type_names(
    tmp_path: Path,
) -> None:
    """The house naming convention the old predicate could not express.

    ``\\b([A-Z][a-z]+[A-Z][A-Za-z]+)\\b`` requires a capital, a LOWERCASE
    run, then another capital, so it matched none of these four names. The
    check then saw fewer than three candidate terms and returned NA — a
    CLAUDE.md naming four uncovered types read as "sample too small".
    """
    _write(
        tmp_path / "CLAUDE.md",
        "Key concepts: ADRReviewPanel, PRPort, CIMonitorLoop, LLMClient.\n",
    )
    _write(tmp_path / "docs" / "wiki" / "architecture.md", "Unrelated text.\n")
    assert _run("P2.9", _ctx(tmp_path)).status is Status.WARN


def test_ubiquitous_language_credits_covered_leading_acronym_terms(
    tmp_path: Path,
) -> None:
    """The other direction: seeing them must not mean always warning."""
    _write(
        tmp_path / "CLAUDE.md",
        "Key concepts: ADRReviewPanel, PRPort, CIMonitorLoop, LLMClient.\n",
    )
    _write(
        tmp_path / "docs" / "wiki" / "architecture.md",
        "ADRReviewPanel, PRPort, CIMonitorLoop and LLMClient are documented.\n",
    )
    assert _run("P2.9", _ctx(tmp_path)).status is Status.PASS


def test_ubiquitous_language_still_ignores_all_caps_prose(tmp_path: Path) -> None:
    """Widening must not turn ``TDD``/``README``/``CI`` into vocabulary."""
    _write(
        tmp_path / "CLAUDE.md",
        "Read the README. TDD is the default. CI runs on every PR. Always.\n",
    )
    _write(tmp_path / "docs" / "wiki" / "architecture.md", "Unrelated text.\n")
    assert _run("P2.9", _ctx(tmp_path)).status is Status.NA


def test_ubiquitous_language_na_when_docs_missing(tmp_path: Path) -> None:
    assert _run("P2.9", _ctx(tmp_path)).status is Status.NA


def test_ubiquitous_language_passes_when_terms_in_split_topic_files(
    tmp_path: Path,
) -> None:
    """Terms scattered across ``architecture-*.md`` topic files still resolve.

    Mirrors the layout introduced by PR #8462 — ``architecture.md`` carries
    the entry-point reference table for a few terms, the rest live in topic
    files. The audit must read them all, not just the residual entry file.
    """
    _write(
        tmp_path / "CLAUDE.md",
        "Key concepts: TaskRunner, IssueTracker, LabelMachine, PhaseGuard.\n",
    )
    _write(
        tmp_path / "docs" / "wiki" / "architecture.md",
        "Entry-point page; mentions TaskRunner.\n",
    )
    _write(
        tmp_path / "docs" / "wiki" / "architecture-layers.md",
        "Layer doc covers IssueTracker and LabelMachine in depth.\n",
    )
    _write(
        tmp_path / "docs" / "wiki" / "architecture-state-persistence.md",
        "PhaseGuard semantics and storage.\n",
    )
    assert _run("P2.9", _ctx(tmp_path)).status is Status.PASS
