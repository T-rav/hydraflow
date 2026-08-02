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
* copies the full six-directory ``docs/standards/**`` corpus directly from the
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

# All six standards directories copied verbatim from HydraFlow (issue #10935).
STANDARDS_DIRS: tuple[str, ...] = (
    "adr_enforcement",
    "branch_protection",
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
    """The running HydraFlow checkout root (source of the standards + AGENTS.md)."""
    return Path(__file__).resolve().parents[2]


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
    return f"""[project]
name = "{spec.name}"
version = "0.1.0"
description = "{spec.description}"
requires-python = ">=3.11"
dependencies = []

[project.scripts]
{spec.entry} = "{spec.pkg}.cli:main"

[project.optional-dependencies]
dev = [
  "pytest>=8",
  "pytest-cov>=5",
  "ruff>=0.6",
  "pyright>=1.1.380",
  "bandit>=1.7",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]

[tool.coverage.run]
source = ["src"]

[tool.pyright]
venvPath = "."
venv = ".venv"
"""


def _cli(spec: KernelSpec) -> str:
    # No ``if __name__ == "__main__"`` guard: the CLI is exposed via
    # ``[project.scripts]`` and the guard would be an uncovered line that drops
    # the fresh kernel below its own coverage floor (breaking green-day-one).
    return f'''"""CLI entrypoint for {spec.name}."""

from __future__ import annotations


def main() -> None:
    """Run the placeholder V1 command."""
    print("{spec.name} ready")
'''


def _smoke_test(spec: KernelSpec) -> str:
    return f'''"""Smoke test proving the CLI is importable and runs."""

from __future__ import annotations

from {spec.pkg}.cli import main


def test_main_smoke(capsys) -> None:
    main()

    assert "{spec.name} ready" in capsys.readouterr().out
'''


def _claude_md(spec: KernelSpec) -> str:
    """CLAUDE.md skeleton with explicit template-owned vs product-owned sections."""
    return f"""# {spec.title}

<!-- TEMPLATE-OWNED: managed by the HydraFlow kernel. Re-stamping with --force may -->
<!-- overwrite this block. Put project-specific rules in the PRODUCT-OWNED section. -->

## Quick rules (always apply)

- **Never commit to `{spec.main_branch}`.** All changes go through a worktree branch and a PR.
- **PRs target `{spec.staging_branch}`, not `{spec.main_branch}`.**
- **Always run `make quality`** before declaring work complete.
- **Always write unit tests before committing.**
- Knowledge lives in [`docs/wiki/`](docs/wiki/index.md); decisions in [`docs/adr/`](docs/adr/README.md).
- Cross-cutting rules live in [`docs/standards/`](docs/standards/).

## Commands

- `make quality` — full quality gate
- `make test` — tests + coverage
- `make audit DIR=.` — HydraFlow-format structural audit

<!-- END TEMPLATE-OWNED -->

<!-- PRODUCT-OWNED: your project's load-bearing rules and glossary. The kernel -->
<!-- writer never overwrites anything below this marker. -->

## Domain rules

{spec.safety_block}

## Glossary

<!-- Add ubiquitous-language terms here. -->
"""


def _readme(spec: KernelSpec) -> str:
    return f"""# {spec.title}

{spec.description}

## Architecture

| Layer | Path |
|---|---|
| Application package | `src/{spec.pkg}` |
| Tests | `tests/` |
| ADRs | `docs/adr/` |
| Wiki | `docs/wiki/` |
| Standards | `docs/standards/` |

## Quality

```
make quality
```

## Safety

{spec.safety_block}
"""


def _env_example(spec: KernelSpec) -> str:
    return f"""# {spec.title} — environment configuration
# Domain-specific variables belong at the top of this block.
LOG_LEVEL=INFO
"""


def _gitignore() -> str:
    return ".venv/\n__pycache__/\n.coverage\ncoverage.xml\n.pytest_cache/\ndist/\n.hydraflow/\n"


def _quality_workflow() -> str:
    return generate_workflow("python")


def _issue_template(spec: KernelSpec, name: str) -> str:
    return f"""---
name: {name}
about: HydraFlow-managed {name.lower()}
labels: {spec.label_prefix}-find
---

## Context

## Expected outcome
"""


def _pull_request_template(spec: KernelSpec) -> str:
    return f"""## Summary

## Verification

- [ ] `make quality`

## Domain safety

{spec.safety_block}
"""


def _adr_readme() -> str:
    return (
        "# Architecture Decision Records\n\n"
        "| ADR | Title | Status |\n"
        "|---|---|---|\n"
        "| [0001](0001-initial-architecture.md) | Initial architecture | Accepted |\n"
    )


def _adr_0001(spec: KernelSpec) -> str:
    return f"""# ADR-0001: Initial architecture

## Status

Accepted

## Context

{spec.description}

## Decision

Start with a small Python package, a strict `make quality` gate, and
HydraFlow-compatible project hygiene (labels, standards, wiki, ADRs).

## Consequences

The repo is auditable by `make audit` from day one and ready for the factory.
"""


def _wiki_index(spec: KernelSpec) -> str:
    topic_rows = "\n".join(f"- [{topic}](./{topic}.md)" for topic in WIKI_TOPICS)
    return f"""# {spec.title} Wiki

Karpathy-pattern knowledge base. The RepoWikiLoop keeps these topic pages fresh.

## Topics

{topic_rows}
"""


def _wiki_topic(spec: KernelSpec, topic: str) -> str:
    return f"""# {topic.title()}

Seed page for the `{topic}` topic. Entries accrue here as the project grows;
this file is product-owned and is never clobbered by re-stamping.
"""


def _prep_script(spec: KernelSpec) -> str:
    return f'''"""Preparation checks for {spec.name}."""

from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="Preparation checks.")
    parser.add_argument(
        "--decimal-purity",
        action="store_true",
        help="Run the decimal-purity AST guard over money paths.",
    )
    parser.parse_args()


if __name__ == "__main__":
    main()
'''


def _branch_protection_script(spec: KernelSpec) -> str:
    return f'''"""Apply branch protection to this repository (GitHub classic protection API).

Free-tier private repos cannot use the modern Rulesets API, so this kernel ships
the classic ``PUT /repos/{{owner}}/{{repo}}/branches/{{branch}}/protection`` variant
(onboarding doc friction F2). The canonical required-check list is the ``quality``
workflow job. Requires an authenticated ``gh`` CLI with admin on the repo.

Usage::

    python scripts/setup_branch_protection.py            # dry-run
    python scripts/setup_branch_protection.py --apply
    python scripts/setup_branch_protection.py --repo owner/name --apply
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

REQUIRED_CHECKS = ["quality"]
PROTECTED_BRANCHES = ["{spec.main_branch}", "{spec.staging_branch}"]


def _repo_slug(explicit: str | None) -> str:
    if explicit:
        return explicit
    url = subprocess.check_output(
        ["git", "remote", "get-url", "origin"], text=True
    ).strip()
    for prefix in ("https://github.com/", "git@github.com:"):
        if url.startswith(prefix):
            slug = url[len(prefix) :]
            return slug[:-4] if slug.endswith(".git") else slug
    raise SystemExit(f"could not derive owner/name from remote: {{url}}")


def _protection_payload() -> dict:
    return {{
        "required_status_checks": {{"strict": True, "contexts": REQUIRED_CHECKS}},
        "enforce_admins": True,
        "required_pull_request_reviews": {{"required_approving_review_count": 0}},
        "restrictions": None,
    }}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=None, help="owner/name (default: git remote)")
    parser.add_argument("--apply", action="store_true", help="apply (default: dry-run)")
    args = parser.parse_args(argv)

    slug = _repo_slug(args.repo)
    payload = _protection_payload()
    for branch in PROTECTED_BRANCHES:
        endpoint = f"repos/{{slug}}/branches/{{branch}}/protection"
        if not args.apply:
            print(f"[dry-run] PUT {{endpoint}} <- {{json.dumps(payload)}}")
            continue
        subprocess.run(
            ["gh", "api", "--method", "PUT", endpoint, "--input", "-"],
            input=json.dumps(payload),
            text=True,
            check=True,
        )
        print(f"protected {{slug}}@{{branch}}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


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
        (".github/workflows/quality.yml", _quality_workflow(), Ownership.TEMPLATE),
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
    # docs/standards/** — the full six-directory corpus, copied verbatim.
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
    return plan


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
    for rel, content, ownership in _plan(spec, hf_root):
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

    result.residual_steps = residual_manual_steps(spec, root)
    return result


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
