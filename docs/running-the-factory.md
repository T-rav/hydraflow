# Running the factory without dirtying your checkout

The factory mutates the directory it runs from (`config.repo_root`): the wiki,
arch, and runtime-cache loops write artifacts into the working tree as they
operate, and each maintenance PR is built in an *ephemeral* worktree
(`auto_pr.open_automated_pr_async`) that never cleans the originals. If you run
`make run` from the same checkout you develop in, that checkout is permanently
dirty.

## Use a dedicated workspace

```bash
make factory
```

This runs `scripts/run-factory-isolated.sh`, which:

1. Clones the repo (once) into a dedicated workspace —
   `~/.hydraflow/factory-workspace/hydraflow` by default.
2. Hard-syncs that workspace to the latest base branch (`main` by default) on
   every launch — the workspace is the factory's scratch space, so its churn is
   discarded here.
3. Copies your dev checkout's `.env` into the workspace so credentials/config
   carry over.
4. Launches the server (`make run`) from the workspace.

Your dev checkout is never touched. The factory's PRs still land on `origin` as
usual; pull them into your clean checkout with `git pull`.

### Overrides

| Env var | Default | Purpose |
|---|---|---|
| `HYDRAFLOW_FACTORY_WORKSPACE` | `~/.hydraflow/factory-workspace/hydraflow` | Where the dedicated clone lives |
| `HYDRAFLOW_FACTORY_BRANCH` | `main` | Branch the factory runs |

## Why not just `git restore` after each run?

The runtime caches (`docs/wiki/log.jsonl`, `ingest_dedup.json`, `index.json`)
are now gitignored, and the maintenance loops will be taught to self-clean after
their PR merges — but isolating the workspace is the robust catch-all: a fresh
writer that forgets to clean up can't dirty a checkout it never touches.
