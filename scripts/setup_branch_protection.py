"""Apply HydraFlow's standard branch-protection rulesets to a GitHub repo.

The rulesets encode ADR-0042's two-tier branch model (counts are generated
from ``gates.toml``; see the README's generated gate table, not this prose):
- ``main protect`` (targets ``refs/heads/main``): merge-commit only, with the
  full standard CI set plus the RC promotion + MockWorld + e2e gate.
- ``staging protect`` (targets ``refs/heads/staging``): squash or merge, with
  the always-on baseline checks (heavy jobs run but are path-filter-safe).

Canonical configs live at ``docs/standards/branch_protection/*.json``, are
generated from ``gates.toml`` (ADR-0082), and are version-controlled. This script is the apply-er — idempotent: ``PUT``
on a ruleset that already exists by name, ``POST`` if absent.

Usage::

    # Auto-detect repo from `git remote get-url origin`
    python scripts/setup_branch_protection.py            # dry-run
    python scripts/setup_branch_protection.py --apply
    python scripts/setup_branch_protection.py --audit    # diff live vs canonical

    # Explicit repo
    python scripts/setup_branch_protection.py --repo owner/name --apply

The script also enables ``allow_auto_merge=true`` at the repo level and
creates a ``staging`` branch from the default branch HEAD if missing.

Requires ``gh`` CLI authenticated with at least ``repo`` scope and admin on
the target repo.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_DIR = REPO_ROOT / "docs/standards/branch_protection"

# Share one drift-detection core with BranchProtectionAuditorLoop (ADR-0082).
sys.path.insert(0, str(REPO_ROOT))
from src.branch_protection_audit import (  # noqa: E402
    diff_ruleset,
    load_canonical,
)


def _gh(*args: str, input_data: str | None = None) -> str:
    """Run ``gh`` and return stdout. Raises on non-zero."""
    result = subprocess.run(
        ["gh", *args],
        input=input_data,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        sys.stderr.write(f"gh {' '.join(args)} failed:\n{result.stderr}\n")
        raise SystemExit(result.returncode)
    return result.stdout


def _detect_repo() -> str:
    """Return ``owner/name`` from git remote, or exit with help."""
    try:
        url = subprocess.check_output(
            ["git", "remote", "get-url", "origin"], text=True
        ).strip()
    except subprocess.CalledProcessError:
        sys.stderr.write("Could not run `git remote get-url origin` — pass --repo.\n")
        raise SystemExit(2) from None
    # Handle https://github.com/owner/name(.git) and git@github.com:owner/name(.git)
    for prefix in ("https://github.com/", "git@github.com:"):
        if url.startswith(prefix):
            slug = url[len(prefix) :]
            if slug.endswith(".git"):
                slug = slug[:-4]
            return slug
    sys.stderr.write(f"Could not parse owner/name from {url!r} — pass --repo.\n")
    raise SystemExit(2)


def _load_canonical() -> dict[str, dict[str, Any]]:
    return load_canonical(CANONICAL_DIR)


def _existing_rulesets(repo: str) -> dict[str, dict[str, Any]]:
    """Map ruleset name → full ruleset (resolved) for the repo."""
    listing = json.loads(_gh("api", f"/repos/{repo}/rulesets"))
    out: dict[str, dict[str, Any]] = {}
    for entry in listing:
        full = json.loads(_gh("api", f"/repos/{repo}/rulesets/{entry['id']}"))
        out[entry["name"]] = full
    return out


def _list_branch_names(repo: str) -> set[str]:
    """All branch names for ``repo``, following pagination.

    ``gh api --paginate`` walks every page; ``--jq '.[].name'`` emits one name
    per line across all pages. Without pagination, a repo with more than one
    page of branches (30 per page by default) reads ``staging`` as missing when
    it sits past the first page.
    """
    out = _gh("api", "--paginate", f"/repos/{repo}/branches", "--jq", ".[].name")
    return {line for line in out.splitlines() if line}


def _diff(canonical: dict[str, Any], live: dict[str, Any]) -> list[str]:
    """Human-readable drift lines (empty = clean).

    Delegates to the shared core in ``src.branch_protection_audit`` so the CLI
    and ``BranchProtectionAuditorLoop`` use one drift-detection implementation.
    """
    return diff_ruleset(canonical, live)


def _ensure_staging_branch(repo: str, default_branch: str, *, apply: bool) -> str:
    """Return action description; create the branch if --apply and missing."""
    names = _list_branch_names(repo)
    if "staging" in names:
        return "  staging branch: already present, no change"
    head = json.loads(_gh("api", f"/repos/{repo}/branches/{default_branch}"))
    head_sha = head["commit"]["sha"]
    if not apply:
        return f"  staging branch: WOULD create from {default_branch}@{head_sha[:8]}"
    _gh(
        "api",
        "-X",
        "POST",
        f"/repos/{repo}/git/refs",
        "-f",
        "ref=refs/heads/staging",
        "-f",
        f"sha={head_sha}",
    )
    return f"  staging branch: created from {default_branch}@{head_sha[:8]} ✓"


def _ensure_auto_merge(repo: str, *, apply: bool) -> str:
    repo_meta = json.loads(_gh("api", f"/repos/{repo}"))
    if repo_meta.get("allow_auto_merge"):
        return "  allow_auto_merge: already true, no change"
    if not apply:
        return "  allow_auto_merge: WOULD set false → true"
    _gh("api", "-X", "PATCH", f"/repos/{repo}", "-F", "allow_auto_merge=true")
    return "  allow_auto_merge: false → true ✓"


def _apply_rulesets(
    repo: str,
    canonical: dict[str, dict[str, Any]],
    existing: dict[str, dict[str, Any]],
    *,
    apply: bool,
) -> list[str]:
    out: list[str] = []
    for name, cfg in canonical.items():
        live = existing.get(name)
        if live is None:
            if not apply:
                out.append(f"  ruleset {name!r}: WOULD create (POST)")
                continue
            response = _gh(
                "api",
                "-X",
                "POST",
                f"/repos/{repo}/rulesets",
                "--input",
                "-",
                input_data=json.dumps(cfg),
            )
            new_id = json.loads(response)["id"]
            out.append(f"  ruleset {name!r}: created (id={new_id}) ✓")
            continue
        diffs = _diff(cfg, live)
        if not diffs:
            out.append(f"  ruleset {name!r}: live matches canonical, no change")
            continue
        if not apply:
            out.append(f"  ruleset {name!r}: WOULD update (PUT) — drift detected")
            continue
        ruleset_id = live["id"]
        _gh(
            "api",
            "-X",
            "PUT",
            f"/repos/{repo}/rulesets/{ruleset_id}",
            "--input",
            "-",
            input_data=json.dumps(cfg),
        )
        out.append(f"  ruleset {name!r}: updated (id={ruleset_id}) ✓")
    return out


def _audit(
    repo: str,
    canonical: dict[str, dict[str, Any]],
    existing: dict[str, dict[str, Any]],
) -> int:
    """Return exit code: 0 clean, 1 drift detected."""
    print(f"Audit: {repo}")
    repo_meta = json.loads(_gh("api", f"/repos/{repo}"))
    drift = False
    if not repo_meta.get("allow_auto_merge"):
        print("  ✗ allow_auto_merge=false (canonical: true)")
        drift = True
    else:
        print("  ✓ allow_auto_merge=true")
    branches = _list_branch_names(repo)
    if "staging" not in branches:
        print("  ✗ staging branch missing")
        drift = True
    else:
        print("  ✓ staging branch present")
    for name, cfg in canonical.items():
        live = existing.get(name)
        if live is None:
            print(f"  ✗ ruleset {name!r} missing")
            drift = True
            continue
        diffs = _diff(cfg, live)
        if diffs:
            print(f"  ✗ ruleset {name!r} drift:")
            for line in diffs:
                print(f"      {line}")
            drift = True
        else:
            print(f"  ✓ ruleset {name!r} matches canonical")
    return 1 if drift else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        help="GitHub repo as owner/name (auto-detected from `git remote` if omitted)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes (default is dry-run)",
    )
    parser.add_argument(
        "--audit",
        action="store_true",
        help="Compare live config to canonical; exit 1 on drift. Implies dry-run.",
    )
    args = parser.parse_args()

    repo = args.repo or _detect_repo()
    canonical = _load_canonical()
    existing = _existing_rulesets(repo)

    if args.audit:
        return _audit(repo, canonical, existing)

    repo_meta = json.loads(_gh("api", f"/repos/{repo}"))
    default_branch = repo_meta["default_branch"]

    print(f"Repo: {repo}  (default branch: {default_branch})")
    print(f"Mode: {'APPLY' if args.apply else 'DRY-RUN (use --apply to write)'}")
    print()
    print(_ensure_staging_branch(repo, default_branch, apply=args.apply))
    print(_ensure_auto_merge(repo, apply=args.apply))
    for line in _apply_rulesets(repo, canonical, existing, apply=args.apply):
        print(line)

    return 0


if __name__ == "__main__":
    sys.exit(main())
