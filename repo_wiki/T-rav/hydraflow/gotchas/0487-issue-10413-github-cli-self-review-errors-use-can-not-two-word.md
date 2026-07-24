---
id: 0487
topic: gotchas
source_issue: 10413
source_phase: plan
created_at: 2026-07-24T06:07:17.313460+00:00
status: superseded
corroborations: 1
superseded_by: 0494
---

# GitHub CLI self-review errors use "can not" (two words), not "cannot"

GitHub's live `addPullRequestReview` GraphQL error is `Review Can not approve your own pull request` / `Can not request changes on your own pull request` — two words, not "cannot". `PRManager.submit_review` (`src/pr_manager.py` ~L1382) matched the one-word `cannot` variant, so the classifier never fired and every bot-PR self-approve fell through to a `Could not submit review` WARNING + `return False` instead of the intended `SelfReviewError` skip.

**Why:** string-matching third-party CLI/API error text against an assumed spelling silently breaks classification without raising — always pin the match against the real wire message, not a guessed one.
