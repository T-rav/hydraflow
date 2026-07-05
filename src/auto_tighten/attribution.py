from __future__ import annotations

from collections.abc import Callable


class AttributionResolver:
    def __init__(self, list_merged_prs: Callable[[str], list[dict]]) -> None:
        self._list = list_merged_prs

    def attribute(self, paths_of_interest: list[str], since_iso: str) -> int | None:
        for pr in self._list(since_iso):
            for f in pr.get("files", []):
                if any(f.startswith(p) for p in paths_of_interest):
                    return int(pr["number"])
        return None
