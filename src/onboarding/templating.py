"""Local materialization for HydraFlow-format repository bootstrap drafts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from charter import (
    Articles,
    Artifacts,
    Charter,
    PolicyBlock,
    Purpose,
    RailsBlock,
    default_autonomy_policy,
    render_charter,
)
from onboarding.kernel_templates import render
from onboarding.models import BootstrapSpec

METHODOLOGY_REF = "docs/methodology/onboarding-hydraflow-format-repos.md"


@dataclass(frozen=True)
class MaterializedFile:
    """A file written by the templating service."""

    path: str
    bytes_written: int


@dataclass(frozen=True)
class MaterializeResult:
    """Result of writing a draft repository to disk."""

    root: Path
    files: tuple[MaterializedFile, ...]
    events: tuple[dict[str, str], ...]


class MaterializeError(RuntimeError):
    """Raised when local materialization cannot safely proceed."""


def package_name_for(spec: BootstrapSpec) -> str:
    """Return the import package name for *spec*."""

    if spec.package_name:
        candidate = spec.package_name.strip().lower().replace("-", "_")
    else:
        candidate = spec.name.replace("-", "_")
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,99}", candidate):
        raise MaterializeError("package_name must be a valid Python package name")
    return candidate


def materialize_repository(spec: BootstrapSpec, parent_dir: Path) -> MaterializeResult:
    """Write the deterministic bootstrap kernel for *spec* under *parent_dir*."""

    parent = parent_dir.expanduser().resolve()
    target = parent / spec.name
    if target.exists() and any(target.iterdir()):
        raise MaterializeError(
            f"target directory already exists and is not empty: {target}"
        )
    target.mkdir(parents=True, exist_ok=True)

    package_name = package_name_for(spec)
    generated_at = datetime.now(UTC).isoformat()
    context = _TemplateContext(
        spec=spec, package_name=package_name, generated_at=generated_at
    )
    files = _render_files(context)
    written: list[MaterializedFile] = []
    for relative_path, content in files.items():
        destination = target / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        data = content.encode()
        destination.write_bytes(data)
        written.append(MaterializedFile(path=relative_path, bytes_written=len(data)))

    return MaterializeResult(
        root=target,
        files=tuple(written),
        events=(
            {"level": "info", "message": "materialized invariant kernel"},
            {"level": "info", "message": f"wrote {len(written)} files"},
        ),
    )


@dataclass(frozen=True)
class _TemplateContext:
    spec: BootstrapSpec
    package_name: str
    generated_at: str

    @property
    def cli_entry(self) -> str:
        return self.spec.name.replace("-", "_")

    @property
    def project_title(self) -> str:
        return self.spec.name.replace("-", " ").title()

    @property
    def safety_block(self) -> str:
        if not self.spec.safety_guards:
            return "- Keep V1 deliberately small and covered by tests."
        return "\n".join(f"- {guard}" for guard in self.spec.safety_guards)


def wizard_frontmatter(ctx: _TemplateContext) -> str:
    """Return the wizard-draft frontmatter required by the factory handshake."""
    return render("wizard/frontmatter.md.tmpl", generated_at=ctx.generated_at)


def _render_files(ctx: _TemplateContext) -> dict[str, str]:
    package = ctx.package_name
    return {
        ".env.example": render("wizard/env.example.tmpl", title=ctx.project_title),
        ".gitignore": render("wizard/gitignore.tmpl"),
        "Makefile": _makefile(ctx),
        "pyproject.toml": _pyproject(ctx),
        "README.md": _readme(ctx),
        "CLAUDE.md": _claude_md(ctx),
        f"src/{package}/__init__.py": render("wizard/pkg_init.py.tmpl"),
        f"src/{package}/cli.py": _cli(ctx),
        "tests/unit/test_smoke.py": _smoke_test(ctx),
        ".github/workflows/quality.yml": _quality_workflow(ctx),
        ".github/ISSUE_TEMPLATE/bug.md": _issue_template(ctx, "Bug report"),
        ".github/ISSUE_TEMPLATE/feature.md": _issue_template(ctx, "Feature request"),
        ".github/PULL_REQUEST_TEMPLATE.md": _pull_request_template(ctx),
        "charter.yaml": _charter(ctx),
        "docs/adr/README.md": render("wizard/adr_README.md.tmpl"),
        "docs/adr/0001-initial-architecture.md": _adr(ctx),
        "docs/standards/testing.md": render("wizard/standards_testing.md.tmpl"),
        "docs/wiki/index.md": _wiki(ctx),
        "scripts/__init__.py": render("wizard/scripts_init.py.tmpl"),
        "scripts/prep.py": _prep_script(ctx),
        "scripts/setup_branch_protection.py": _branch_protection_script(),
        "docs/specs/bootstrap-spec.md": wizard_frontmatter(ctx) + _spec_doc(ctx),
        "docs/plans/plan-01-bootstrap.md": wizard_frontmatter(ctx) + _plan_doc(ctx),
    }


def _charter(ctx: _TemplateContext) -> str:
    """Render the new repo's ``charter.yaml`` — its governing declaration.

    A materialized repo is governed from its first commit rather than from a
    later retrofit (ADR-0143's Articles layer; ADR-0121 Ruling 2 for the
    ``rails:`` block).

    Every field declares only what this template actually writes. The
    ``universal`` layer is deliberately **not** declared: its marker is the
    HydraFlow principles ADR, which the kernel stamp delivers and this
    bootstrap does not — declaring it here would make a brand-new repo drift
    on its first audit. ``articles.standards`` is empty for the same reason:
    the bootstrap writes a loose ``docs/standards/testing.md``, and a standard
    id resolves to a *directory*.
    """
    charter = Charter(
        purpose=Purpose(product=ctx.spec.description),
        articles=Articles(standards=()),
        artifacts=Artifacts(required=("docs/adr", "docs/wiki", "tests")),
        # Declared here as well as in `charter_from_snapshot` (#12116). This is
        # the from-scratch bootstrap; that one is the stamp onto an existing
        # repo. A charter written without it is not broken — the merge gate
        # falls through to the same shipped default — but the repo's governing
        # declaration would then be silent about how it governs merges, and
        # "governed from its first commit" above would be true of every layer
        # except the one that decides what may merge.
        policy=PolicyBlock(present=True, data=default_autonomy_policy()),
        rails=RailsBlock(
            template_version="1",
            layers=("language_pack",),
            coverage_floor=float(ctx.spec.coverage_floor),
        ),
    )
    return render_charter(charter)


def _pyproject(ctx: _TemplateContext) -> str:
    return render(
        "wizard/pyproject.toml.tmpl",
        cli_entry=ctx.cli_entry,
        description=ctx.spec.description,
        name=ctx.spec.name,
        pkg=ctx.package_name,
    )


def _safety_target(ctx: _TemplateContext) -> str:
    """The decimal-purity `quality` prerequisite, when that guard is on."""
    guards = {guard.lower() for guard in ctx.spec.safety_guards}
    if "decimal-purity" not in guards:
        return ""
    return "\n\tuv run python scripts/prep.py --decimal-purity\n"


def _makefile(ctx: _TemplateContext) -> str:
    return render(
        "wizard/Makefile.tmpl",
        coverage_floor=ctx.spec.coverage_floor,
        safety_target=_safety_target(ctx),
    )


def _quality_workflow(ctx: _TemplateContext) -> str:
    return render(
        "wizard/quality.yml.tmpl",
        main_branch=ctx.spec.main_branch,
        staging_branch=ctx.spec.staging_branch,
    )


def _readme(ctx: _TemplateContext) -> str:
    return render(
        "wizard/README.md.tmpl",
        description=ctx.spec.description,
        pkg=ctx.package_name,
        safety_block=ctx.safety_block,
        title=ctx.project_title,
    )


def _claude_md(ctx: _TemplateContext) -> str:
    return render(
        "wizard/CLAUDE.md.tmpl",
        safety_block=ctx.safety_block,
        title=ctx.project_title,
    )


def _cli(ctx: _TemplateContext) -> str:
    return render("wizard/cli.py.tmpl", name=ctx.spec.name)


def _smoke_test(ctx: _TemplateContext) -> str:
    return render("wizard/test_smoke.py.tmpl", name=ctx.spec.name, pkg=ctx.package_name)


def _issue_template(ctx: _TemplateContext, name: str) -> str:
    return render(
        "wizard/issue_template.md.tmpl",
        kind=name,
        kind_lower=name.lower(),
        label_prefix=ctx.spec.label_prefix,
    )


def _pull_request_template(ctx: _TemplateContext) -> str:
    return render("wizard/pull_request_template.md.tmpl", safety_block=ctx.safety_block)


def _adr(ctx: _TemplateContext) -> str:
    return render("wizard/adr_0001.md.tmpl", description=ctx.spec.description)


def _wiki(ctx: _TemplateContext) -> str:
    return render("wizard/wiki_index.md.tmpl", title=ctx.project_title)


def _prep_script(ctx: _TemplateContext) -> str:
    return render("wizard/prep.py.tmpl", name=ctx.spec.name)


def _branch_protection_script() -> str:
    return render("wizard/branch_protection.py.tmpl")


def _spec_doc(ctx: _TemplateContext) -> str:
    return render(
        "wizard/spec_doc.md.tmpl",
        description=ctx.spec.description,
        name=ctx.spec.name,
        title=ctx.project_title,
    )


def _plan_doc(ctx: _TemplateContext) -> str:
    return render("wizard/plan_doc.md.tmpl", title=ctx.project_title)
