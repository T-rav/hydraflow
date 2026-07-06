from auto_tighten.models import ConfirmedTightening, FileEdit
from auto_tighten.pr_author import TighteningPrAuthor


async def test_open_calls_opener_with_auto_merge(tmp_path):
    (tmp_path / "pyproject.toml").write_text("fail_under = 70\n")
    captured = {}

    async def fake_opener(**kwargs):
        captured.update(kwargs)

        class R:
            pr_url = "https://gh/pr/1"

        return R()

    author = TighteningPrAuthor(repo_root=tmp_path, base="staging", opener=fake_opener)
    ct = ConfirmedTightening(
        ratchet_id="coverage",
        floor=77.0,
        file_edits=[
            FileEdit(
                path=str(tmp_path / "pyproject.toml"), new_text="fail_under = 77\n"
            )
        ],
        dedup_key="coverage:77.0",
        evidence="PR #11",
    )
    url = await author.open(ct)
    assert url == "https://gh/pr/1"
    assert captured["auto_merge"] is True
    assert captured["base"] == "staging"
    assert (tmp_path / "pyproject.toml").read_text() == "fail_under = 77\n"


async def test_open_returns_none_when_result_lacks_pr_url(tmp_path):
    (tmp_path / "pyproject.toml").write_text("fail_under = 70\n")

    async def fake_opener(**kwargs):
        class R:
            pass

        return R()

    author = TighteningPrAuthor(repo_root=tmp_path, base="staging", opener=fake_opener)
    ct = ConfirmedTightening(
        ratchet_id="coverage",
        floor=77.0,
        file_edits=[
            FileEdit(
                path=str(tmp_path / "pyproject.toml"), new_text="fail_under = 77\n"
            )
        ],
        dedup_key="coverage:77.0",
        evidence="PR #11",
    )
    url = await author.open(ct)
    assert url is None


async def test_branch_name_sanitized_for_unsafe_dedup_key(tmp_path):
    (tmp_path / "new_dir" / "pyproject.toml").parent.mkdir(parents=True, exist_ok=True)
    captured = {}

    async def fake_opener(**kwargs):
        captured.update(kwargs)

        class R:
            pr_url = "https://gh/pr/2"

        return R()

    author = TighteningPrAuthor(repo_root=tmp_path, base="staging", opener=fake_opener)
    ct = ConfirmedTightening(
        ratchet_id="coverage",
        floor=77.0,
        file_edits=[
            FileEdit(
                path=str(tmp_path / "new_dir" / "pyproject.toml"),
                new_text="fail_under = 77\n",
            )
        ],
        dedup_key="foo/bar baz:1.0",
        evidence="PR #11",
    )
    url = await author.open(ct)
    assert url == "https://gh/pr/2"
    branch = captured["branch"]
    assert branch.startswith("auto-tighten/")
    dynamic_segment = branch[len("auto-tighten/") :]
    assert "/" not in dynamic_segment
    assert " " not in dynamic_segment
