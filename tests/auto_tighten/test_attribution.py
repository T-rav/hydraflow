from auto_tighten.attribution import AttributionResolver

PRS = [
    {"number": 10, "files": ["docs/readme.md"], "merged_at": "2026-07-01T00:00:00Z"},
    {"number": 11, "files": ["tests/test_foo.py"], "merged_at": "2026-07-02T00:00:00Z"},
]


def test_attributes_pr_touching_paths():
    r = AttributionResolver(list_merged_prs=lambda since: PRS)
    assert r.attribute(["tests/", "src/"], since_iso="2026-06-30T00:00:00Z") == 11


def test_returns_none_when_no_touch():
    r = AttributionResolver(list_merged_prs=lambda since: [PRS[0]])
    assert r.attribute(["tests/", "src/"], since_iso="2026-06-30T00:00:00Z") is None


def test_returns_first_match_when_multiple_prs_match():
    prs = [{"number": 5, "files": ["src/a.py"]}, {"number": 9, "files": ["tests/b.py"]}]
    r = AttributionResolver(list_merged_prs=lambda since: prs)
    assert r.attribute(["tests/", "src/"], since_iso="x") == 5


def test_forwards_since_iso_to_lister():
    received = {}

    def lister(since):
        received["since"] = since
        return []

    r = AttributionResolver(list_merged_prs=lister)
    r.attribute(["tests/"], since_iso="2026-07-01T00:00:00Z")
    assert received["since"] == "2026-07-01T00:00:00Z"
