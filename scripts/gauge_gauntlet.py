#!/usr/bin/env python3
"""Gauge gauntlet — execute the scaffold rails for real, or say UNEXERCISED.

Slice 2 of #11060. The Phase-0 audit found the scaffold's nine language gauges
were tested only as *strings* — nothing ever ran eslint/tsc/cargo/gradle — the
fake-fidelity sentinel failure mode at gauge scale. This gauntlet is the
detonator range: per requested gauge it builds a minimal fixture repo in a
temp dir, lays the gauge's rails (the real scaffolds — ``stamp_kernel`` for
Python, ``generate_makefile`` for the rest), then EXECUTES the quality
commands a stamped child would run. A gauge either passes for real or fails
loudly.

Gauges not requested are reported ``UNEXERCISED`` by name — never silently
skipped (the no-silent-caps rule). Today only ``python`` and ``javascript``
have executable fixtures; the other seven stay honestly UNEXERCISED until an
engagement demands them (#11060 slice 5 territory).

Advisory by design: wired as the "Gauge Gauntlet (advisory)" CI lane, never
in ci-gate's needs (per #9922).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from makefile_scaffold import generate_makefile  # noqa: E402
from onboarding.kernel_writer import KernelSpec, stamp_kernel  # noqa: E402

#: Every gauge the scaffold claims (mirrors makefile_scaffold's template map,
#: minus the "node" alias for "javascript").
KNOWN_GAUGES: tuple[str, ...] = (
    "python",
    "javascript",
    "java",
    "ruby",
    "rails",
    "csharp",
    "go",
    "rust",
    "cpp",
)

#: Gauges with an executable fixture today. Everything else is UNEXERCISED.
EXECUTABLE_GAUGES: frozenset[str] = frozenset({"python", "javascript"})

#: Per-command ceiling. npm/uv installs dominate; nothing may idle-hang past it.
COMMAND_TIMEOUT_SECONDS = 600


def js_fixture_files() -> dict[str, str]:
    """The minimal-but-real JavaScript/TypeScript fixture (flat-config eslint)."""
    package = {
        "name": "gauge-js-fixture",
        "private": True,
        "type": "module",
        "devDependencies": {
            "typescript": "^5.5.0",
            "eslint": "^9.0.0",
            "typescript-eslint": "^8.0.0",
            "vitest": "^3.0.0",
        },
    }
    tsconfig = {
        "compilerOptions": {
            "strict": True,
            "noEmit": True,
            "target": "ES2022",
            "module": "ES2022",
            "moduleResolution": "bundler",
            "skipLibCheck": True,
        },
        "include": ["src", "tests"],
    }
    return {
        "package.json": json.dumps(package, indent=2) + "\n",
        "tsconfig.json": json.dumps(tsconfig, indent=2) + "\n",
        "eslint.config.mjs": (
            'import tseslint from "typescript-eslint";\n'
            "export default tseslint.config(...tseslint.configs.recommended);\n"
        ),
        "src/index.ts": (
            "export function add(a: number, b: number): number {\n  return a + b;\n}\n"
        ),
        "tests/index.test.ts": (
            'import { describe, expect, it } from "vitest";\n'
            'import { add } from "../src/index.js";\n\n'
            'describe("add", () => {\n'
            '  it("adds", () => {\n'
            "    expect(add(2, 3)).toBe(5);\n"
            "  });\n"
            "});\n"
        ),
        "Makefile": generate_makefile("javascript"),
    }


def write_js_fixture(child: Path) -> None:
    for rel, content in js_fixture_files().items():
        dest = child / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")


def write_python_fixture(child: Path) -> None:
    """The Python gauge IS the stamped kernel — exercise the real thing."""
    stamp_kernel(
        KernelSpec(name="gauge-python-fixture", package_name="gaugefix"), child
    )


def plan_commands(gauge: str) -> list[list[str]]:
    """The commands a child on this gauge runs for its quality rails.

    Python goes through ``uv run`` so the child's own synced venv supplies the
    tools (exactly the stamped developer flow); JavaScript relies on npx
    resolving the fixture's local node_modules.
    """
    if gauge == "python":
        # The stamped child's tooling lives in its `dev` extra (see
        # kernel_writer._pyproject) — the first real gauntlet run caught this
        # exact mismatch, which is the lane doing its job.
        return [
            ["uv", "sync", "--extra", "dev", "--quiet"],
            ["uv", "run", "make", "lint-check"],
            ["uv", "run", "make", "typecheck"],
            ["uv", "run", "make", "security"],
            ["uv", "run", "make", "test"],
        ]
    if gauge == "javascript":
        return [
            ["npm", "install", "--no-fund", "--no-audit", "--loglevel=error"],
            ["make", "lint-check"],
            ["make", "typecheck"],
            ["make", "security"],
            ["make", "test"],
        ]
    return []


_FIXTURE_WRITERS: dict[str, Callable[[Path], None]] = {
    "python": write_python_fixture,
    "javascript": write_js_fixture,
}


@dataclass(frozen=True, slots=True)
class GaugeResult:
    gauge: str
    status: str  # "PASS" | "FAIL" | "UNEXERCISED" | "UNKNOWN"
    detail: str = ""


def run_gauge(
    gauge: str,
    workdir: Path,
    *,
    runner: Callable[[list[str], Path], subprocess.CompletedProcess[str]] | None = None,
) -> GaugeResult:
    """Lay the gauge's rails in a fresh child under *workdir* and execute them."""
    if gauge not in KNOWN_GAUGES:
        return GaugeResult(gauge, "UNKNOWN", "not a scaffold gauge")
    if gauge not in EXECUTABLE_GAUGES:
        return GaugeResult(gauge, "UNEXERCISED", "no executable fixture yet")
    child = workdir / f"child-{gauge}"
    child.mkdir(parents=True, exist_ok=True)
    _FIXTURE_WRITERS[gauge](child)
    execute = runner or _subprocess_runner
    for command in plan_commands(gauge):
        result = execute(command, child)
        if result.returncode != 0:
            tail = (result.stdout or "") + (result.stderr or "")
            return GaugeResult(
                gauge,
                "FAIL",
                f"`{' '.join(command)}` exit {result.returncode}: {tail[-800:]}",
            )
    return GaugeResult(gauge, "PASS")


def _subprocess_runner(
    command: list[str], cwd: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=COMMAND_TIMEOUT_SECONDS,
        check=False,
    )


def summarize(results: list[GaugeResult]) -> tuple[str, int]:
    """Render the verdict table + the exit code (fail iff a REQUESTED gauge failed)."""
    lines = ["gauge gauntlet (#11060 slice 2):"]
    for result in results:
        lines.append(f"  {result.status:<11} {result.gauge}")
        if result.detail and result.status == "FAIL":
            lines.append(f"    {result.detail}")
    unexercised = [r.gauge for r in results if r.status == "UNEXERCISED"]
    if unexercised:
        lines.append(
            "  note: UNEXERCISED gauges have never executed — their scaffold "
            "recipes are unproven strings until a fixture lands (#11060)."
        )
    exit_code = 1 if any(r.status in ("FAIL", "UNKNOWN") for r in results) else 0
    return "\n".join(lines) + "\n", exit_code


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Execute scaffold gauges for real (advisory lane, #11060)."
    )
    parser.add_argument(
        "--gauges",
        default="python",
        help="Comma-separated gauges to EXECUTE; all others report UNEXERCISED.",
    )
    parser.add_argument(
        "--keep", action="store_true", help="Keep the temp fixtures for inspection."
    )
    args = parser.parse_args()

    requested = [g.strip() for g in args.gauges.split(",") if g.strip()]
    workdir = Path(tempfile.mkdtemp(prefix="gauge-gauntlet-"))
    try:
        results = [run_gauge(gauge, workdir) for gauge in requested]
        results += [
            GaugeResult(gauge, "UNEXERCISED", "not requested this run")
            for gauge in KNOWN_GAUGES
            if gauge not in requested
        ]
        output, exit_code = summarize(results)
        print(output, end="")
        if args.keep:
            print(f"fixtures kept at {workdir}")
        return exit_code
    finally:
        if not args.keep:
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
