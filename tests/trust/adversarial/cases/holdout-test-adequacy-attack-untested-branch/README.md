# holdout-test-adequacy-attack-untested-branch

HOLDOUT honeypot case — never shown to the refiner. A new `retries > 3`
branch is added to `compute_backoff_seconds` with no accompanying test
change. Test adequacy must flag this untested branch.

Keyword: untested branch
