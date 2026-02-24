"""Build the bundled assets archive used by `hf init`."""

from __future__ import annotations

import argparse
import tarfile
from pathlib import Path

from hf_cli.assets_manifest import ASSET_PATHS


def bundle_assets(output: Path, root: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "w:gz") as tar:
        for rel_path in ASSET_PATHS:
            abs_path = root / rel_path
            if not abs_path.exists():
                raise FileNotFoundError(f"Asset path missing: {abs_path}")
            tar.add(abs_path, arcname=str(rel_path))
    print(f"Bundled assets → {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Bundle HydraFlow assets for hf init")
    parser.add_argument(
        "--output",
        default=Path("hf_cli/assets.tar.gz"),
        type=Path,
        help="Path to the generated tar.gz",
    )
    parser.add_argument(
        "--root",
        default=Path.cwd(),
        type=Path,
        help="Repo root containing asset directories",
    )
    args = parser.parse_args()
    bundle_assets(args.output, args.root)


if __name__ == "__main__":
    main()
