---
id: 1100
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T02:29:25.908727+00:00
status: active
corroborations: 1
supersedes: 1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1030,1031,1032,1033,1034,1035,1036,1037,1038,1039,1040,1041,1042,1043,1044,1045,1046,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1057,1058,1059,1060,1061,1062,1063,1064,1065,1066,1067,1068,1069,1070,1071,1072,1073,1074,1075,1076,1077,1078,1079,1080,1081,1082,1083,1084
---

# Exclude `.git` when scanning fixture dirs for contract fakes

Any helper that walks cassette.fixture_repo to build fake git output (e.g. _root_commit_summary() in test_fake_git_contract.py) must filter with ".git" not in p.parts.

Example: include .gitkeep and other dotfiles (no special-casing needed); exclude only the .git/ path segment.

**Why:** a stray .git/ left behind from an in-place record_git run corrupts file/insertion counts in the generated commit summary, since pathlib glob happily includes dotfiles/dotdirs like .gitkeep and .git alike.
