"""Pure readers: GitHub text and config strings turned into typed values.

Every function here is total, side-effect free, and takes only what it
parses. The two compiled patterns live WITH their single consumer — a
regex left behind while its function moved is the classic split defect,
and it fails as a ``NameError`` inside a broad handler rather than at
import (#11658).

They are grouped because they share a failure mode, not a topic: each one
turns something GitHub or a config file hands us as a string into
something the rest of the module can trust, and each one silently returns
an empty result when the input shape changes.
"""

from __future__ import annotations

import logging
import re

from config import HydraFlowConfig
from models import (
    MergeStrategy,
)

logger = logging.getLogger("hydraflow.epic")


def _stage_from_labels(labels: list[str], config: HydraFlowConfig) -> str:
    """Derive pipeline stage name from issue labels."""
    label_set = set(labels)
    if label_set & set(config.review_label):
        return "review"
    if label_set & set(config.ready_label):
        return "implement"
    if label_set & set(config.planner_label):
        return "plan"
    if label_set & set(config.find_label):
        return "triage"
    if label_set & set(config.fixed_label):
        return "merged"
    return ""


# Matches checkbox lines like "- [ ] #123 — title" or "- [x] #456 — title"
_CHECKBOX_PATTERN = re.compile(r"- \[[ x]\] #(\d+)")


def _coerce_merge_strategy(value: str | MergeStrategy) -> MergeStrategy:
    """Normalise config/state merge strategy values to the enum."""
    if isinstance(value, MergeStrategy):
        return value
    text = str(value).strip().lower()
    try:
        return MergeStrategy(text)
    except ValueError:
        logger.warning(
            "Unknown merge_strategy %r; falling back to 'independent'", value
        )
        return MergeStrategy.INDEPENDENT


def parse_epic_sub_issues(body: str) -> list[int]:
    """Extract unique issue numbers from checkbox lines in an epic body, preserving first-occurrence order."""
    return list(dict.fromkeys(int(m) for m in _CHECKBOX_PATTERN.findall(body)))


def check_all_checkboxes(body: str) -> str:
    """Replace all unchecked checkboxes with checked ones for issue references."""
    return re.sub(r"- \[ \] (#\d+)", r"- [x] \1", body)


# Matches version strings requiring either a "v" prefix (v1, v1.2, v1.2.3)
# or multi-part notation (1.2, 1.2.3) to avoid matching bare integers like
# "Phase 3" or "Sprint 5".
_VERSION_PATTERN = re.compile(r"v(\d+(?:\.\d+)*)|\b(\d+\.\d+(?:\.\d+)*)\b")


def extract_version_from_title(title: str) -> str:
    """Extract a semantic version string from an epic title.

    Looks for patterns like "v1.2.0", "1.0", "v2" in the title.
    Requires either a 'v' prefix or multi-part notation to avoid matching
    bare integers (e.g. "Phase 3" would not extract "3").
    Returns the matched version (without 'v' prefix) or empty string.
    """
    match = _VERSION_PATTERN.search(title)
    return (match.group(1) or match.group(2)) if match else ""
