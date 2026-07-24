---
id: 0633
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T12:09:28.512279+00:00
status: active
corroborations: 1
supersedes: 0545,0546,0547,0548,0549,0550,0551,0552,0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566,0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583,0584,0585,0586,0587,0588,0589,0590,0591,0592
---

# GitHub CLI self-review errors use "can not" (two words), not "cannot"

GitHub's live `addPullRequestReview` GraphQL error is `Review Can not approve your own pull request` / `Can not request changes on your own pull request` — two words, not "cannot".

Example: `PRManager.submit_review` (`src/pr_manager.py` ~L1382) matched the one-word `cannot` variant, so the classifier never fired and every bot-PR self-approve fell through to a `Could not submit review` WARNING + `return False` instead of the intended `SelfReviewError` skip.

**Why:** String-matching third-party CLI/API error text against an assumed spelling silently breaks classification without raising — always pin the match against the real wire message, not a guessed one.
