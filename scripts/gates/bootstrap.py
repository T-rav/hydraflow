"""Init-time gate bootstrap: detect a repo's profile, resolve its gate set.

Used when onboarding a repo to HydraFlow: detect the repo's languages and
capabilities, resolve the gate contract for that profile, and render both the
``[repo]`` block to write into ``gates.toml`` and a human-readable section for
the adoption plan (so the operator sees which checks apply and which dimensions
have no bindable binding before applying branch protection).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace
from pathlib import Path

from scripts.gates.capabilities import detect_capabilities
from scripts.gates.contract import Contract, RepoProfile
from scripts.gates.coverage import unsatisfied_dimensions
from scripts.gates.resolve import resolve_contexts


def _default_detect_langs(repo_root: Path) -> set[str]:
    from src.language_detector import detect_languages

    return detect_languages(repo_root)


def build_repo_profile(
    repo_root: Path,
    repo_slug: str | None,
    *,
    gh: Callable[..., str] | None = None,
    detect_langs: Callable[[Path], Iterable[str]] | None = None,
) -> RepoProfile:
    """Detected profile: languages from the tree, capabilities from GitHub.

    ``repo_slug`` (owner/name) is needed to probe capabilities; without it the
    profile carries languages only.
    """
    langs = (detect_langs or _default_detect_langs)(repo_root)
    if repo_slug is None:
        caps: frozenset[str] = frozenset()
    elif gh is None:
        caps = detect_capabilities(repo_slug)
    else:
        caps = detect_capabilities(repo_slug, gh=gh)
    return RepoProfile(languages=sorted(langs), capabilities=sorted(caps))


def render_repo_profile_toml(profile: RepoProfile) -> str:
    """The ``[repo]`` block to write into gates.toml."""
    langs = ", ".join(f'"{x}"' for x in profile.languages)
    caps = ", ".join(f'"{x}"' for x in profile.capabilities)
    return f"[repo]\nlanguages = [{langs}]\ncapabilities = [{caps}]\n"


def gates_plan_section(profile: RepoProfile, contract: Contract) -> list[str]:
    """Adoption-plan markdown: resolved gate set + gaps + apply commands."""
    resolved = replace(contract, repo=profile)
    lines = [
        "## Branch-protection gates (ADR-0082)",
        "",
        f"Detected for this repo: languages {profile.languages or '[none]'}, "
        f"capabilities {profile.capabilities or '[none]'}.",
        "",
    ]
    if not profile.languages:
        lines += [
            "WARNING: no languages were detected, so every (language-scoped) gate "
            "resolves to empty below. Re-run detection or set the `[repo]` "
            "languages explicitly before applying protection.",
            "",
        ]
    lines.append("Required checks resolved from the gate contract:")
    for branch in sorted(resolved.branches):
        contexts = resolve_contexts(resolved, branch)
        joined = ", ".join(f"`{c}`" for c in contexts) or "(none)"
        lines.append(f"- `{branch}` ({len(contexts)}): {joined}")
    lines.append("")

    gaps = sorted(
        {
            d
            for branch in resolved.branches
            for d in unsatisfied_dimensions(resolved, branch)
        }
    )
    if gaps:
        lines += [
            f"WARNING: unsatisfied required dimensions for this profile: "
            f"{', '.join(gaps)}.",
            "Add an active OSS fallback binding (for example Semgrep for SAST, "
            "pip-audit/osv-scanner for dependency CVEs) or the dimension cannot "
            "be enforced. Never leave a required dimension silently unbound.",
            "",
        ]

    lines += [
        "To apply:",
        "",
        "1. Write the detected profile into "
        "`docs/standards/branch_protection/gates.toml`:",
        "",
        "   ```toml",
        *[f"   {line}" for line in render_repo_profile_toml(profile).splitlines()],
        "   ```",
        "",
        "2. Regenerate artifacts and apply protection:",
        "",
        "   ```bash",
        "   make gen-gates",
        "   python scripts/setup_branch_protection.py --apply",
        "   ```",
        "",
    ]
    return lines
