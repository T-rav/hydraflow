---
id: 0891
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:15:44.742869+00:00
status: active
corroborations: 1
supersedes: 0764,0765,0766,0767,0768,0769,0770,0771,0772,0773,0774,0775,0776,0777,0778,0779,0780,0781,0782,0783,0784,0785,0786,0787,0788,0789,0790,0791,0792,0793,0794,0795,0796,0797,0798,0799,0800,0801,0802,0803,0804,0805,0806,0807,0808,0809,0810,0811,0812,0813,0814,0815,0816,0817,0818,0819,0820,0821,0822,0823,0824,0826,0827,0828,0829,0830,0833,0834,0838,0839,0840,0841,0842,0843,0844,0848,0848,0848,0849,0850
---

# GitHub CLI self-review errors use "can not" (two words), not "cannot"

GitHub's live `addPullRequestReview` GraphQL error is `Review Can not approve your own pull request` / `Can not request changes on your own pull request` — two words, not "cannot".

Example: `PRManager.submit_review` (`src/pr_manager.py` ~L1382) matched the one-word `cannot` variant, so the classifier never fired and every bot-PR self-approve fell through to a `Could not submit review` WARNING + `return False` instead of the intended `SelfReviewError` skip.

**Why:** String-matching third-party CLI/API error text against an assumed spelling silently breaks classification without raising — always pin the match against the real wire message, not a guessed one.
