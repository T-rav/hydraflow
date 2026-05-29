"""Generate branch-protection artifacts from gates.toml, or --check for drift.

Writes the per-branch ruleset JSON and the gate table inside the generated block
in README.md. ``--check`` renders in memory, diffs against the committed files,
and runs validate(); it exits 1 on any difference or orphan-producer violation.

    python -m scripts.gen_gates            # write artifacts
    python -m scripts.gen_gates --check    # CI: fail on drift

Run as a module from the repo root so ``scripts.gates`` resolves as a package.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scripts.gates.contract import Contract, load_gates
from scripts.gates.coverage import unsatisfied_dimensions
from scripts.gates.docs_table import render_docs_table
from scripts.gates.resolve import render_ruleset
from scripts.gates.validate import validate
from scripts.gates.workflow_jobs import index_workflow_jobs

BP = Path("docs/standards/branch_protection")
CONTRACT = BP / "gates.toml"
README = BP / "README.md"
WORKFLOWS = Path(".github/workflows")
BEGIN = "<!-- generated:gates -->"
END = "<!-- /generated:gates -->"


def _ruleset_text(contract: Contract, branch: str) -> str:
    return json.dumps(render_ruleset(contract, branch), indent=2) + "\n"


def _readme_with_block(contract: Contract, current: str) -> str:
    block = f"{BEGIN}\n{render_docs_table(contract)}\n{END}"
    start = current.index(BEGIN)
    end = current.index(END) + len(END)
    return current[:start] + block + current[end:]


def _artifacts(contract: Contract) -> dict[Path, str]:
    return {
        BP / "main_ruleset.json": _ruleset_text(contract, "main"),
        BP / "staging_ruleset.json": _ruleset_text(contract, "staging"),
        README: _readme_with_block(contract, README.read_text()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="diff only; exit 1 on drift"
    )
    args = parser.parse_args()

    contract = load_gates(CONTRACT)
    violations = validate(contract, index_workflow_jobs(WORKFLOWS))
    for branch in contract.branches:
        for dim in unsatisfied_dimensions(contract, branch):
            violations.append(
                f"branch {branch!r}: dimension {dim!r} has no bindable active gate "
                f"for the [repo] profile (language/capability mismatch)"
            )
    artifacts = _artifacts(contract)

    if args.check:
        problems = list(violations)
        for path, text in artifacts.items():
            if path.read_text() != text:
                problems.append(
                    f"STALE: {path} differs from gates.toml; run `make gen-gates`"
                )
        if problems:
            print("\n".join(problems), file=sys.stderr)
            return 1
        print("gates: artifacts and workflow producers in sync")
        return 0

    for path, text in artifacts.items():
        path.write_text(text)
    if violations:
        print("\n".join(violations), file=sys.stderr)
        return 1
    print("gates: wrote main_ruleset.json, staging_ruleset.json, README table")
    return 0


if __name__ == "__main__":
    sys.exit(main())
