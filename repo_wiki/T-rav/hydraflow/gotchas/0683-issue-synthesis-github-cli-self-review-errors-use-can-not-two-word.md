---
id: 0683
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:40:13.481712+00:00
status: superseded
corroborations: 1
supersedes: 0593,0594,0595,0596,0597,0598,0599,0600,0601,0602,0603,0604,0605,0606,0607,0608,0609,0610,0611,0612,0613,0614,0615,0616,0617,0618,0619,0620,0621,0622,0623,0624,0625,0626,0627,0628,0629,0630,0631,0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642
superseded_by: 0704
---

# GitHub CLI self-review errors use "can not" (two words), not "cannot"

GitHub's live `addPullRequestReview` GraphQL error is `Review Can not approve your own pull request` / `Can not request changes on your own pull request` — two words, not "cannot".

Example: `PRManager.submit_review` (`src/pr_manager.py` ~L1382) matched the one-word `cannot` variant, so the classifier never fired and every bot-PR self-approve fell through to a `Could not submit review` WARNING + `return False` instead of the intended `SelfReviewError` skip.

**Why:** String-matching third-party CLI/API error text against an assumed spelling silently breaks classification without raising — always pin the match against the real wire message, not a guessed one.
