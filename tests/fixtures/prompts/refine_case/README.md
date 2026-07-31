# diff-sanity regression: silent truncation reads as "no change"

The skill must flag a diff whose hunk header claims more lines than the body
carries. A truncated diff is not an empty diff, and treating it as one lets a
partial change through review as though nothing happened.
