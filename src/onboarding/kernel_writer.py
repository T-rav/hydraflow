"""Greenfield kernel writer — stamp the invariant kernel for a new HydraFlow-format repo.

This is the ``make stamp`` payload writer. Given a target directory and a few
substitution variables (``pkg`` / ``description`` / ``cli_entry`` /
``coverage_floor``) it materializes the full invariant kernel documented in
``docs/methodology/onboarding-hydraflow-format-repos.md`` — the file set that was
structurally identical across the two reference bootstraps (amplifier, harvestd).

Relationship to ``onboarding.templating.materialize_repository``
---------------------------------------------------------------
``templating.materialize_repository`` is the *wizard/API* materializer (Phase 1
of the onboarding roadmap): it renders a slimmer draft kernel inline for the
``/api/onboarding`` flow and adds wizard-draft spec/plan docs. This module is the
*CLI* ``make stamp`` path and is the single source of truth for the greenfield
kernel. It deliberately differs from ``templating`` in the ways issue #10935
called out as gaps in that module:

* reuses the real scaffolders (``makefile_scaffold`` / ``ci_scaffold``) instead of
  duplicating Makefile / CI YAML inline,
* copies the full kernel ``docs/standards/**`` corpus directly from the
  running HydraFlow checkout rather than writing a single testing doc,
* ships ``AGENTS.md`` and the five ``RepoWikiLoop`` topic pages,
* enforces per-file, ownership-aware idempotency (product-owned files are never
  clobbered on re-stamp).

The two modules are kept separate on purpose; this docstring is the anchor that
keeps them from silently diverging into two competing kernel definitions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from ci_scaffold import generate_workflow
from makefile_scaffold import generate_makefile
from onboarding.kernel_lock import (
    KERNEL_LOCK_FILENAME,
    build_lock,
    dump_lock,
)
from onboarding.kernel_templates import render
from package_resources import checkout_path

METHODOLOGY_REF = "docs/methodology/onboarding-hydraflow-format-repos.md"

# The five canonical RepoWikiLoop topic pages (``repo_wiki.DEFAULT_TOPICS``).
# These double as the P1.3-P1.7 documentation-spine audit checks.
WIKI_TOPICS: tuple[str, ...] = (
    "architecture",
    "patterns",
    "gotchas",
    "testing",
    "dependencies",
)

# The kernel standards corpus, copied verbatim from HydraFlow (issue #10935).
# Bound to the kernel table in docs/standards/factory_operation/README.md by
# tests/architecture/test_factory_operation_standard_drift.py, which also
# asserts the two tables partition docs/standards/ exactly — so a new standard
# directory cannot land in neither.
STANDARDS_DIRS: tuple[str, ...] = (
    "adr_enforcement",
    "branch_protection",
    "exception_sensor",
    "factory_autonomy",
    "factory_operation",
    "ports-and-loops",
    "testing",
)

_PACKAGE_NAME_RE = re.compile(r"[a-z][a-z0-9_]{1,99}")


class KernelWriterError(RuntimeError):
    """Raised when the kernel cannot be stamped safely."""


class Ownership(StrEnum):
    """Who owns a stamped file after it lands in the target repo.

    ``TEMPLATE`` files are invariant kernel plumbing — safe to re-stamp with
    ``force=True``. ``PRODUCT`` files accrue project-specific content (CLAUDE.md
    product sections, ADRs, wiki entries, deps in pyproject) and are *never*
    overwritten by re-stamping, even under ``force``.
    """

    TEMPLATE = "template"
    PRODUCT = "product"


@dataclass(frozen=True)
class KernelSpec:
    """Substitution variables for the greenfield kernel.

    Mirrors the onboarding doc's invariant-table variables: ``pkg`` /
    ``description`` / ``cli_entry`` / ``coverage_floor`` plus the optional
    domain-rail slots (safety guards, label prefix, branch names).
    """

    name: str
    package_name: str | None = None
    description: str = "A HydraFlow-format repository."
    cli_entry: str | None = None
    coverage_floor: int = 80
    safety_guards: tuple[str, ...] = ()
    label_prefix: str = "hydraflow"
    main_branch: str = "main"
    staging_branch: str = "staging"
    # Optional councils-of-personas layer (#10949): stamp the agents/ skeleton
    # (persona contracts + council charter + decisions/ record discipline) per
    # docs/methodology/councils-of-personas.md. Off by default — chartering
    # review chambers is a deliberate project choice, not kernel plumbing.
    # Named `agents_console` until the 2026-08-25 house rename (ARCH-0003);
    # `spec_from_lock` still reads the old key so pre-rename child locks
    # keep resolving to the same prescription.
    agents_council: bool = False

    @property
    def pkg(self) -> str:
        """The validated import package name."""
        raw = self.package_name if self.package_name else self.name
        candidate = raw.strip().lower().replace("-", "_")
        if not _PACKAGE_NAME_RE.fullmatch(candidate):
            raise KernelWriterError(
                f"package name is not a valid Python identifier: {candidate!r}"
            )
        return candidate

    @property
    def entry(self) -> str:
        """The console-script entry-point name."""
        if self.cli_entry:
            return self.cli_entry.strip()
        return self.name.replace("-", "_")

    @property
    def title(self) -> str:
        return self.name.replace("-", " ").replace("_", " ").title()

    @property
    def safety_block(self) -> str:
        if not self.safety_guards:
            return "- Keep V1 deliberately small and covered by tests."
        return "\n".join(f"- {guard}" for guard in self.safety_guards)

    @property
    def has_decimal_purity(self) -> bool:
        return "decimal-purity" in {g.strip().lower() for g in self.safety_guards}


@dataclass(frozen=True)
class StampedFile:
    """A single file the kernel writer considered."""

    path: str
    ownership: Ownership
    action: str  # "written" | "rewritten" | "skipped" | "protected"


@dataclass
class StampResult:
    """Outcome of a stamp run."""

    root: Path
    files: list[StampedFile] = field(default_factory=list)
    residual_steps: list[str] = field(default_factory=list)

    @property
    def written(self) -> list[StampedFile]:
        return [f for f in self.files if f.action in ("written", "rewritten")]

    @property
    def skipped(self) -> list[StampedFile]:
        return [f for f in self.files if f.action in ("skipped", "protected")]

    def paths(self) -> set[str]:
        return {f.path for f in self.files}


def _hydraflow_root() -> Path:
    """The running HydraFlow checkout root (source of the standards + AGENTS.md).

    ``AGENTS.md`` and ``docs/standards/`` are checkout content, not package
    data, so stamping a kernel needs a real clone; from an installed wheel
    this raises rather than reading an empty ``site-packages`` (#11589).
    """
    return checkout_path()


def _makefile(spec: KernelSpec) -> str:
    """Reuse ``makefile_scaffold`` and parameterize by coverage floor + guards.

    The base Python Makefile is green day one: ``make test`` emits a ``coverage.xml``
    artifact that ``coverage-check`` reads, and the smoke test exercises the CLI so
    the fresh kernel clears its own floor.
    """
    base = generate_makefile("python")
    if not base:  # pragma: no cover - python is always a known language
        raise KernelWriterError("makefile scaffolder returned no Python Makefile")
    floor = spec.coverage_floor
    base = base.replace("COVERAGE_MIN ?= 70", f"COVERAGE_MIN ?= {floor}")
    base = base.replace("COVERAGE_TARGET ?= 70", f"COVERAGE_TARGET ?= {floor}")
    # Emit a coverage artifact so `coverage-check` has an input on day one.
    base = base.replace(
        "\tpytest tests/ -x -q\n",
        "\tpytest tests/ -x -q --cov=src --cov-report=xml --cov-report=term-missing\n",
    )
    if spec.has_decimal_purity:
        base = base.rstrip("\n") + "\n"
        base += "\n.PHONY: decimal-purity\n"
        base += "decimal-purity:\n\tpython scripts/prep.py --decimal-purity\n"
        # Accumulate decimal-purity as a `quality` prerequisite (prereq-only line).
        base += "quality: decimal-purity\n"
    return base


def _pyproject(spec: KernelSpec) -> str:
    return render(
        "pyproject.toml.tmpl",
        description=spec.description,
        entry=spec.entry,
        name=spec.name,
        pkg=spec.pkg,
    )


def _cli(spec: KernelSpec) -> str:
    return render("cli.py.tmpl", name=spec.name)


def _smoke_test(spec: KernelSpec) -> str:
    return render("test_smoke.py.tmpl", name=spec.name, pkg=spec.pkg)


def _claude_md(spec: KernelSpec) -> str:
    """CLAUDE.md skeleton with explicit template-owned vs product-owned sections."""
    return render(
        "CLAUDE.md.tmpl",
        main_branch=spec.main_branch,
        safety_block=spec.safety_block,
        staging_branch=spec.staging_branch,
        title=spec.title,
    )


def _readme(spec: KernelSpec) -> str:
    return render(
        "README.md.tmpl",
        description=spec.description,
        pkg=spec.pkg,
        safety_block=spec.safety_block,
        title=spec.title,
    )


def _env_example(spec: KernelSpec) -> str:
    return render("env.example.tmpl", title=spec.title)


def _gitignore() -> str:
    return render("gitignore.tmpl")


def _quality_workflow(spec: KernelSpec) -> str:
    """The stamped quality workflow, triggering on every protected branch.

    Both branches matter: ``scripts/setup_branch_protection.py`` protects
    `main` AND `staging` with the same required context, and the stamped
    CLAUDE.md tells agents to target `staging`. A workflow that only triggered
    on `main` would leave that context unreported on every feature PR (#11715).
    """
    return generate_workflow("python", branches=(spec.main_branch, spec.staging_branch))


def _issue_template(spec: KernelSpec, name: str) -> str:
    return render(
        "issue_template.md.tmpl",
        kind=name,
        kind_lower=name.lower(),
        label_prefix=spec.label_prefix,
    )


def _pull_request_template(spec: KernelSpec) -> str:
    return render("pull_request_template.md.tmpl", safety_block=spec.safety_block)


def _adr_readme() -> str:
    return render("adr_README.md.tmpl")


def _adr_0001(spec: KernelSpec) -> str:
    return render("adr_0001.md.tmpl", description=spec.description)


def _wiki_index(spec: KernelSpec) -> str:
    return render("wiki_index.md.tmpl", title=spec.title)


def _wiki_topic(spec: KernelSpec, topic: str) -> str:
    return render("wiki_topic.md.tmpl", topic=topic, topic_title=topic.title())


def _prep_script(spec: KernelSpec) -> str:
    return render("prep.py.tmpl", name=spec.name)


def _branch_protection_script(spec: KernelSpec) -> str:
    return render(
        "branch_protection.py.tmpl",
        main_branch=spec.main_branch,
        staging_branch=spec.staging_branch,
    )


def _plan(spec: KernelSpec, hydraflow_root: Path) -> list[tuple[str, str, Ownership]]:
    """Return the ordered kernel plan as ``(relative_path, content, ownership)``.

    ``content`` for copied-from-HydraFlow files (standards, AGENTS.md) is read
    lazily in :func:`stamp_kernel`; here it is a sentinel handled specially, so
    every entry that carries real text is materialized inline.
    """
    plan: list[tuple[str, str, Ownership]] = [
        # --- Code skeleton ---
        (
            f"src/{spec.pkg}/__init__.py",
            f'"""{spec.title} — generated by the HydraFlow greenfield kernel writer."""\n',
            Ownership.TEMPLATE,
        ),
        (f"src/{spec.pkg}/cli.py", _cli(spec), Ownership.TEMPLATE),
        ("tests/unit/test_smoke.py", _smoke_test(spec), Ownership.TEMPLATE),
        # --- Config ---
        ("pyproject.toml", _pyproject(spec), Ownership.PRODUCT),
        (".gitignore", _gitignore(), Ownership.TEMPLATE),
        (".env.example", _env_example(spec), Ownership.PRODUCT),
        ("Makefile", _makefile(spec), Ownership.TEMPLATE),
        (".github/workflows/quality.yml", _quality_workflow(spec), Ownership.TEMPLATE),
        # --- Docs ---
        ("CLAUDE.md", _claude_md(spec), Ownership.PRODUCT),
        ("README.md", _readme(spec), Ownership.PRODUCT),
        ("docs/adr/README.md", _adr_readme(), Ownership.PRODUCT),
        ("docs/adr/0001-initial-architecture.md", _adr_0001(spec), Ownership.PRODUCT),
        ("docs/wiki/index.md", _wiki_index(spec), Ownership.PRODUCT),
        (
            ".github/ISSUE_TEMPLATE/bug.md",
            _issue_template(spec, "Bug report"),
            Ownership.TEMPLATE,
        ),
        (
            ".github/ISSUE_TEMPLATE/feature.md",
            _issue_template(spec, "Feature request"),
            Ownership.TEMPLATE,
        ),
        (
            ".github/PULL_REQUEST_TEMPLATE.md",
            _pull_request_template(spec),
            Ownership.TEMPLATE,
        ),
        # --- Scripts ---
        (
            "scripts/__init__.py",
            '"""Project maintenance scripts."""\n',
            Ownership.TEMPLATE,
        ),
        ("scripts/prep.py", _prep_script(spec), Ownership.TEMPLATE),
        (
            "scripts/setup_branch_protection.py",
            _branch_protection_script(spec),
            Ownership.TEMPLATE,
        ),
    ]
    # The five RepoWikiLoop topic pages (product-owned; never clobbered).
    for topic in WIKI_TOPICS:
        plan.append(
            (f"docs/wiki/{topic}.md", _wiki_topic(spec, topic), Ownership.PRODUCT)
        )
    # AGENTS.md — copied verbatim from the running HydraFlow checkout.
    agents_src = hydraflow_root / "AGENTS.md"
    if agents_src.is_file():
        plan.append(
            ("AGENTS.md", agents_src.read_text(encoding="utf-8"), Ownership.TEMPLATE)
        )
    # docs/standards/** — the full kernel corpus, copied verbatim.
    standards_root = hydraflow_root / "docs" / "standards"
    for standard in STANDARDS_DIRS:
        src_dir = standards_root / standard
        if not src_dir.is_dir():
            continue
        for src_file in sorted(src_dir.rglob("*")):
            if not src_file.is_file():
                continue
            rel = src_file.relative_to(hydraflow_root).as_posix()
            plan.append((rel, src_file.read_text(encoding="utf-8"), Ownership.TEMPLATE))
    # Optional councils-of-personas layer (#10949). Skeleton READMEs are
    # TEMPLATE-owned (re-stampable under force); the personas and decision
    # records a project accrues alongside them are its own files and are never
    # part of this plan.
    if spec.agents_council:
        plan.extend(_agents_council_files(spec))
    return plan


def _agents_council_files(spec: KernelSpec) -> list[tuple[str, str, Ownership]]:
    """The councils-of-personas skeleton (#10949): four TEMPLATE-owned READMEs."""
    return [
        (dest, render(f"council/{body}.tmpl", title=spec.title), Ownership.TEMPLATE)
        for dest, body in (
            ("agents/README.md", "agents_README.md"),
            ("agents/personas/README.md", "personas_README.md"),
            ("agents/council/README.md", "council_README.md"),
            ("agents/council/decisions/README.md", "decisions_README.md"),
        )
    ]


def stamp_kernel(
    spec: KernelSpec,
    target_dir: Path,
    *,
    hydraflow_root: Path | None = None,
    force: bool = False,
) -> StampResult:
    """Stamp the invariant kernel for *spec* into *target_dir*.

    Idempotent and ownership-aware: an existing file is never clobbered unless it
    is ``TEMPLATE``-owned and ``force=True``. ``PRODUCT``-owned files (CLAUDE.md,
    README, ADRs, wiki entries, pyproject) are protected even under ``force``.
    """
    root = Path(target_dir).expanduser().resolve()
    hf_root = (hydraflow_root or _hydraflow_root()).resolve()
    root.mkdir(parents=True, exist_ok=True)

    result = StampResult(root=root)
    plan = _plan(spec, hf_root)
    for rel, content, ownership in plan:
        dest = root / rel
        if dest.exists():
            if force and ownership is Ownership.TEMPLATE:
                dest.write_text(content, encoding="utf-8")
                result.files.append(StampedFile(rel, ownership, "rewritten"))
            elif ownership is Ownership.PRODUCT:
                result.files.append(StampedFile(rel, ownership, "protected"))
            else:
                result.files.append(StampedFile(rel, ownership, "skipped"))
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        result.files.append(StampedFile(rel, ownership, "written"))

    # Kernel lock (#11060 slice 1): the child's committed record of WHICH
    # building code stamped it — version + spec + per-file prescribed-content
    # hashes. Written when absent and refreshed whenever its content would
    # differ (a changed prescription, or a diverged/vandalized lock); a
    # byte-identical re-stamp writes nothing, preserving the idempotency
    # contract. This is what lets `make kernel-staleness` distinguish
    # KERNEL_UPDATED from LOCALLY_MODIFIED later.
    lock_content = dump_lock(build_lock(spec_fields=_spec_fields(spec), plan=plan))
    lock_dest = root / KERNEL_LOCK_FILENAME
    if not lock_dest.exists():
        lock_dest.write_text(lock_content, encoding="utf-8")
        lock_action = "written"
    elif lock_dest.read_text(encoding="utf-8", errors="replace") != lock_content:
        lock_dest.write_text(lock_content, encoding="utf-8")
        lock_action = "rewritten"
    else:
        lock_action = "skipped"
    result.files.append(
        StampedFile(KERNEL_LOCK_FILENAME, Ownership.TEMPLATE, lock_action)
    )

    result.residual_steps = residual_manual_steps(spec, root)
    return result


def _spec_fields(spec: KernelSpec) -> dict[str, object]:
    """The spec as lock-serializable fields (enough to recompute the plan)."""
    return {
        "name": spec.name,
        "package_name": spec.package_name,
        "description": spec.description,
        "cli_entry": spec.cli_entry,
        "coverage_floor": spec.coverage_floor,
        "safety_guards": list(spec.safety_guards),
        "label_prefix": spec.label_prefix,
        "main_branch": spec.main_branch,
        "staging_branch": spec.staging_branch,
        "agents_council": spec.agents_council,
    }


def spec_from_lock(lock: dict[str, object]) -> KernelSpec:
    """Rebuild the stamping spec from a child's lock (the staleness read path)."""
    fields_raw = lock.get("spec")
    fields: dict[str, object] = dict(fields_raw) if isinstance(fields_raw, dict) else {}
    return KernelSpec(
        name=str(fields.get("name", "unknown")),
        package_name=(
            str(fields["package_name"])
            if fields.get("package_name") is not None
            else None
        ),
        description=str(fields.get("description", "A HydraFlow-format repository.")),
        cli_entry=(
            str(fields["cli_entry"]) if fields.get("cli_entry") is not None else None
        ),
        coverage_floor=(
            raw_floor
            if isinstance(raw_floor := fields.get("coverage_floor", 80), int)
            else 80
        ),
        safety_guards=(
            tuple(str(guard) for guard in raw_guards)
            if isinstance(raw_guards := fields.get("safety_guards"), list)
            else ()
        ),
        label_prefix=str(fields.get("label_prefix", "hydraflow")),
        main_branch=str(fields.get("main_branch", "main")),
        staging_branch=str(fields.get("staging_branch", "staging")),
        agents_council=bool(
            fields.get("agents_council", fields.get("agents_console", False))
        ),
    )


def prescription(
    spec: KernelSpec, hydraflow_root: Path | None = None
) -> list[tuple[str, str, Ownership]]:
    """The kernel's current prescribed file set for *spec* (public plan access).

    The staleness CLI compares a child's lock against this — the one honest
    source of "what would the building code stamp today."
    """
    return _plan(spec, (hydraflow_root or _hydraflow_root()).resolve())


def residual_manual_steps(spec: KernelSpec, root: Path) -> list[str]:
    """Return the manual steps the operator must run after stamping.

    These are *printed, not automated* per issue #10935 — they create GitHub
    state and must stay a deliberate operator action.
    """
    return [
        f"cd {root}",
        "git init && git add -A && git commit -m 'chore: stamp HydraFlow kernel'",
        f"make setup TARGET_REPO_ROOT={root}   # install agent assets (hooks, AGENTS.md, labels)",
        f"make audit DIR={root}                # verify zero STRUCTURAL FAILs",
        f"gh repo create {spec.name} --{'private'} --source=. --remote=origin --push",
        f"git checkout -b {spec.staging_branch} && git push -u origin {spec.staging_branch}",
        f"# set {spec.staging_branch} as the default branch on GitHub",
        "python scripts/setup_branch_protection.py --apply",
        f"# ensure HydraFlow lifecycle labels ({spec.label_prefix}-*) exist on the repo",
        "# register the new repo with the HydraFlow factory",
    ]
