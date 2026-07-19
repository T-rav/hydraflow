"""Parse ADRs for module:symbol and src/ path references.

Scans every numbered ADR file (e.g. `0001-foo.md`) for occurrences of
`src/<path>.py` or `src/<path>.py:<symbol>`, normalizes each to a dotted
module name (`src.<path>`), and emits a forward index `ADR-NNNN -> [modules]`.
The reverse `module -> [ADRs]` index is computed by the generator.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from pathlib import Path

from arch._models import ADRRef, ADRRefIndex

logger = logging.getLogger(__name__)

_ADR_FILE_RE = re.compile(r"^(\d{4})-.+\.md$")
# Match "src/foo/bar.py", "src/foo/bar.py:Class", "src/foo/bar.py:func_name"
_PATH_REF_RE = re.compile(r"\bsrc/[\w/]+\.py(?::[\w_]+)?")


def _module_from_path_ref(s: str) -> str:
    """`src/foo/bar.py:Class` -> `src.foo.bar`."""
    path_part = s.split(":", 1)[0]
    return path_part.removesuffix(".py").replace("/", ".")


def extract_adr_refs(adr_dir: Path) -> ADRRefIndex:
    adr_dir = Path(adr_dir).resolve()
    # Accumulate the UNION of cited modules per adr_id. Two files can claim the
    # same ADR number (the #9406 collisions); merging here keeps every file's
    # citations instead of letting a dict-keyed downstream consumer silently
    # drop one (issues #9505 / #9465).
    modules_by_id: dict[str, set[str]] = defaultdict(set)
    files_by_id: dict[str, list[str]] = defaultdict(list)
    for md in sorted(adr_dir.glob("*.md")):
        m = _ADR_FILE_RE.match(md.name)
        if not m:
            continue
        adr_id = f"ADR-{m.group(1)}"
        text = md.read_text()
        modules_by_id[adr_id].update(
            _module_from_path_ref(s) for s in _PATH_REF_RE.findall(text)
        )
        files_by_id[adr_id].append(md.name)
    for adr_id, names in files_by_id.items():
        if len(names) > 1:
            logger.warning(
                "Duplicate ADR number %s claimed by %d files: %s. Merging their "
                "cited modules; dict-keyed callers would otherwise drop one — "
                "renumber the later-authored file (issue #9505 / #9465 / #9406).",
                adr_id,
                len(names),
                ", ".join(sorted(names)),
            )
    refs = [
        ADRRef(adr_id=adr_id, cited_modules=sorted(modules_by_id[adr_id]))
        for adr_id in sorted(modules_by_id)
    ]
    return ADRRefIndex(adr_to_modules=refs)
