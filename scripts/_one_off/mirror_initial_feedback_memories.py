"""One-off: generate the initial memory-feedback mirror.

Walks `~/.claude/projects/<repo-encoded>/memory/feedback_*.md`, applies
redactions, writes mirrored copies to `docs/wiki/memory-feedback/`.

Delete this script after the initial PR lands.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
TARGET = REPO_ROOT / "docs" / "wiki" / "memory-feedback"

HOME = Path.home()
SOURCE = HOME / ".claude" / "projects"

# The repo path encoded by Claude Code is the absolute path with `/` -> `-`.
encoded = str(REPO_ROOT.resolve()).replace("/", "-")
# When running from a worktree, the encoded path is for the worktree, not
# the original repo. Fall back to the original encoding if the worktree
# encoding has no memory dir.
SOURCE_DIR_CANDIDATES = [
    SOURCE / encoded / "memory",
    SOURCE / "-Users-travisf-Documents-projects-hydraflow" / "memory",
]


def find_source_dir() -> Path:
    for cand in SOURCE_DIR_CANDIDATES:
        if cand.exists():
            return cand
    msg = "no source memory directory found; tried:\n" + "\n".join(
        f"  - {c}" for c in SOURCE_DIR_CANDIDATES
    )
    raise SystemExit(msg)


def redact(body: str) -> str:
    """Apply redaction rules to memory body text."""
    body = body.replace(str(HOME), "~")
    allowed = ("@anthropic.com", "@hydraflow.local", "@example.com")

    def _email_sub(m: re.Match[str]) -> str:
        addr = m.group(0)
        return addr if any(addr.endswith(suf) for suf in allowed) else "<email>"

    body = re.sub(r"[\w.+-]+@[\w.-]+\.\w+", _email_sub, body)
    return body


_FRONT_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):\s?(.*)$")


def _parse_frontmatter_lenient(block: str) -> dict[str, object]:
    """Parse simple `key: value` frontmatter without strict YAML rules.

    Source memory files sometimes have values that begin with ``backticks``
    or other characters YAML rejects. We only need a flat mapping of the
    top-level scalar fields (`name`, `description`, `type`, `originSessionId`),
    so a line-based parse is both sufficient and more tolerant.
    """
    out: dict[str, object] = {}
    for line in block.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        m = _FRONT_KEY_RE.match(line)
        if not m:
            # Continuation of a folded value or unrecognised — try strict YAML
            # for the whole block as a fallback.
            try:
                loaded = yaml.safe_load(block) or {}
                if isinstance(loaded, dict):
                    return {str(k): v for k, v in loaded.items()}
            except yaml.YAMLError:
                pass
            return out
        key, value = m.group(1), m.group(2).strip()
        # Strip surrounding quotes if present.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        out[key] = value
    return out


def parse_source(path: Path) -> tuple[dict[str, object], str]:
    text = path.read_text()
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end == -1:
        return {}, text
    front = _parse_frontmatter_lenient(text[4:end])
    body = text[end + 4 :].lstrip("\n")
    return front, body


def slug_from_filename(name: str) -> str:
    base = name.removesuffix(".md")
    return base.replace("_", "-")


def main() -> None:
    source_dir = find_source_dir()
    TARGET.mkdir(parents=True, exist_ok=True)
    count = 0
    for src in sorted(source_dir.glob("feedback_*.md")):
        front, body = parse_source(src)
        front.pop("originSessionId", None)
        slug = slug_from_filename(src.name)
        new_front: dict[str, object] = {
            "source": src.name,
            "name": front.get("name", slug),
            "description": front.get("description", ""),
            "status": "pending",
            "issue": None,
            "promoted_in": None,
            "wontfix_reason": None,
            "created": datetime.fromtimestamp(src.stat().st_mtime).date().isoformat(),
        }
        out = (
            "---\n"
            + yaml.safe_dump(
                new_front,
                sort_keys=False,
                allow_unicode=True,
                width=4096,
            ).rstrip()
            + "\n---\n\n"
            + redact(body).rstrip()
            + "\n"
        )
        (TARGET / f"{slug}.md").write_text(out)
        count += 1
    print(f"wrote {count} mirrored memories to {TARGET}", file=sys.stderr)


if __name__ == "__main__":
    main()
