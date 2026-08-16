---
id: 0366
topic: architecture
source_issue: 11292
source_phase: plan
created_at: 2026-08-16T01:48:07.890774+00:00
status: active
corroborations: 1
---

# Class-key fold: marker OR (overlap + needle tokens), never overlap alone

Pattern-shaped findings (one defect class, many sites) fold into ONE open class issue. Use `file_or_fold(prs, source, needle, title, body, labels)` from `src/find_class_key.py` — fold iff `compute_class_key` marker matches exactly OR `title_token_overlap` ≥ `CLASS_OVERLAP_THRESHOLD` (0.5) AND normalized needle tokens appear in candidate body.

- Marker-only wins on exact key match
- Overlap path requires BOTH threshold AND needle-token presence

**Why:** Overlap-only matching produces false folds merging unrelated issues (cross-family title collisions seen in #11188 vs #11281 sibling pairs).
