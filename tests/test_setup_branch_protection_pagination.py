"""Regression: audit must paginate the branch listing (staging false-negative)."""

import scripts.setup_branch_protection as sbp


def test_list_branch_names_paginates(monkeypatch) -> None:
    captured: dict[str, tuple[str, ...]] = {}

    def fake_gh(*args: str, input_data: str | None = None) -> str:
        captured["args"] = args
        # Emulate `gh api --paginate ... --jq '.[].name'`: all names across all
        # pages, one per line. 'staging' sits well past the first 30-item page.
        names = [f"b{i}" for i in range(150)] + ["staging"]
        return "\n".join(names) + "\n"

    monkeypatch.setattr(sbp, "_gh", fake_gh)
    names = sbp._list_branch_names("o/r")

    assert "staging" in names
    # The actual fix: pagination is requested, not a single first-page call.
    assert "--paginate" in captured["args"]
