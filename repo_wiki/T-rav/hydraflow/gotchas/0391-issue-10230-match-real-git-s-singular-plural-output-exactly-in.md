---
id: 0391
topic: gotchas
source_issue: 10230
source_phase: plan
created_at: 2026-07-22T18:13:39.968087+00:00
status: active
corroborations: 1
---

# Match real git's singular/plural output exactly in contract fakes

Git contract fakes replayed against cassettes (`tests/trust/contracts/cassettes/git/*.yaml`) must reproduce git's exact singular/plural phrasing: "1 file changed" vs "N files changed", "1 insertion(+)" vs "M insertions(+)". A 0-line file still emits a `create mode 100644 <relpath>` line but contributes 0 insertions. Getting this wrong fails `test_fake_git_matches_cassette[commit]` even when file counts are otherwise correct, since the harness diffs normalized stdout (`sha:short` normalizer) line-for-line.

**Why:** the contract suite does exact string comparison post-normalization, so plural mismatches are a real failure, not cosmetic.
