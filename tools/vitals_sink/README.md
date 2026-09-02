# vitals sink adapter (#11690, Layer 2 + Layer 3)

`scripts/emit_vitals.py` writes one self-identifying document to stdout and
knows nothing about sinks (#11689, Layer 1). This directory is the other side
of that seam: where such a document lives, and how N of them answer one
question.

It is **outside HydraFlow core** and imports nothing from `src/`. The emitter
imports nothing from here, and `tests/test_vitals_sink.py` fails if it ever
does — that direction is what makes the sink swappable without a HydraFlow
change.

## Decisions

**D1 — push, not pull.** Factories are ephemeral and may be NAT'd. Under push a
dead factory is *visibly absent* from the tree; a scraper cannot miss a host it
never knew existed, so absence would be indistinguishable from health.

**D2 — every RC cut, plus a time floor.** The RC cut is already this repo's
"state changed meaningfully" event, so the trigger needs no new concept. The
floor is what keeps a quiet factory distinguishable from a dead one — without
it, "no new readings" has two meanings.

**D3 — append-only object store, DuckDB for ad-hoc query.** No per-host setup
beyond credentials, no vendor lock, and the JSON is queried where it lies with
no schema migration step. Cardinality is a non-problem here: 868 bytes x 6/day
x 100 factories x 1 year is roughly 200 MB, which is why none of the usual
retention tiering or downsampling exists.

**Not git.** #11676 removed a git-history-derived artifact from git precisely
because content that is a function of the commit graph conflicts on every
rebase, and `merge=union` "resolves" it by duplicating entries. Four-hourly
telemetry from N hosts into a version-controlled tree is that shape, worse.

## Layout

    repo=<slug>/host=<host>/date=<YYYY-MM-DD>/<emitted_at>-<sha7>.json

Hive-style `key=value` segments so DuckDB, Athena and Spark read them as
columns for free. The identity is in the *path*, not only the body, so two
hosts at the same SHA cannot overwrite each other and a query prunes by repo,
host or day without opening a file.

Append-only: the leaf carries the emission instant, and `place()` refuses to
overwrite. Two readings claiming one identity and instant is a fault, not a
retry — absorbing it silently would erase a reading and make "since when?"
unanswerable.

## Use

    # emit and file locally
    PYTHONPATH=src python scripts/emit_vitals.py \
      | python -c "import json,sys;from pathlib import Path;sys.path.insert(0,'tools');\
    from vitals_sink.layout import place;print(place(json.load(sys.stdin),root=Path('vitals')))"

    # ship (any tool — this is deliberately not HydraFlow's problem)
    aws s3 sync vitals/ s3://your-bucket/vitals/     # or rclone, or a mount

    # ask the question
    python tools/vitals_sink/degrading.py vitals/

`degrading.py` is stdlib-only so the question can be answered anywhere the tree
can be read, and tested without a database.

## The same question in DuckDB

For ad-hoc work against a mounted or remote tree:

```sql
WITH readings AS (
  SELECT identity.repo AS repo, identity.host AS host, emitted_at,
         unnest(map_entries(baselines.suppressions)) AS m
  FROM read_json_auto('s3://your-bucket/vitals/**/*.json', filename=true)
),
series AS (
  SELECT repo, host, m.key AS metric, m.value AS value, emitted_at,
         first_value(m.value) OVER w AS first_value
  FROM readings
  WINDOW w AS (PARTITION BY repo, host, m.key ORDER BY emitted_at)
)
SELECT repo, host, metric, first_value AS was, value AS now,
       min(emitted_at) AS since
FROM series
WHERE value > first_value
GROUP BY repo, host, metric, first_value, value
ORDER BY (now - was) DESC;
```

Comparison is always within one `repo, host` partition. Two factories reporting
different numbers are usually two different repos or two different SHAs, and
subtracting those is meaningless.

## What "degrading" means

HydraFlow's baselines are shrink-only ratchets. A rise is not a trend to
interpret — it is a ratchet moving the wrong way. "Since when" is the earliest
reading at or above the current value, never the latest: an operator asking
when it broke is not helped by an answer of "just now" for a week-old
regression.
