"""CLI for ``make stamp`` — stamp the greenfield invariant kernel into a repo.

Thin wrapper over :func:`onboarding.kernel_writer.stamp_kernel`. Writes the full
invariant kernel documented in
``docs/methodology/onboarding-hydraflow-format-repos.md`` into a target directory,
parameterized by ``--pkg`` / ``--description`` / ``--cli-entry`` /
``--coverage-floor``, then prints the residual manual steps (gh repo create,
staging branch, branch protection, labels, factory registration).

Examples::

    python -m scripts.hydraflow_stamp ../new-repo --pkg game1
    python -m scripts.hydraflow_stamp ../new-repo --pkg game1 --coverage-floor 85 --force
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from onboarding.kernel_writer import KernelSpec, KernelWriterError, stamp_kernel


def _default_name(target: Path, pkg: str | None) -> str:
    """Derive a kebab-case repo name from the target dir (or --pkg)."""
    base = target.name or (pkg or "new-repo")
    return base.strip().lower().replace("_", "-")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hydraflow_stamp",
        description="Stamp the greenfield HydraFlow invariant kernel into a repo.",
    )
    parser.add_argument("target", help="Directory to stamp the kernel into.")
    parser.add_argument(
        "--pkg",
        default=None,
        help="Python package name (default: derived from target).",
    )
    parser.add_argument(
        "--name", default=None, help="Repo name (default: target dir name)."
    )
    parser.add_argument(
        "--description",
        default="A HydraFlow-format repository.",
        help="Project description.",
    )
    parser.add_argument(
        "--cli-entry", default=None, help="Console-script entry-point name."
    )
    parser.add_argument(
        "--coverage-floor", type=int, default=80, help="Coverage floor (0-100)."
    )
    parser.add_argument(
        "--safety-guard",
        action="append",
        default=[],
        dest="safety_guards",
        help="Domain safety guard (repeatable), e.g. --safety-guard decimal-purity.",
    )
    parser.add_argument(
        "--label-prefix", default="hydraflow", help="Issue-label prefix."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-stamp template-owned files (product-owned files stay protected).",
    )
    parser.add_argument(
        "--agents-console",
        action="store_true",
        help=(
            "Also stamp the consoles-of-personas skeleton (#10949): agents/ "
            "personas + console charter + decisions/ record discipline."
        ),
    )
    args = parser.parse_args(argv)

    target = Path(args.target).expanduser()
    spec = KernelSpec(
        name=args.name or _default_name(target, args.pkg),
        package_name=args.pkg,
        description=args.description,
        cli_entry=args.cli_entry,
        coverage_floor=args.coverage_floor,
        safety_guards=tuple(args.safety_guards),
        label_prefix=args.label_prefix,
        agents_console=args.agents_console,
    )

    try:
        result = stamp_kernel(spec, target, force=args.force)
    except KernelWriterError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    written = result.written
    skipped = result.skipped
    print(f"Stamped {spec.name} into {result.root}")
    print(f"  {len(written)} file(s) written, {len(skipped)} protected/skipped")
    for item in skipped:
        print(f"  - kept existing {item.path} ({item.ownership.value}-owned)")

    print("\nResidual manual steps (not automated — they create GitHub state):")
    for step in result.residual_steps:
        print(f"  {step}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
