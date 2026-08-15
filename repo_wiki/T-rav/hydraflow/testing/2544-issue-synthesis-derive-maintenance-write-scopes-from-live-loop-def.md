---
id: 2544
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.249506+00:00
status: active
corroborations: 1
supersedes: 2355
---

# Derive maintenance write scopes from live loop definitions

Read each loop's write scope from its canonical source: wiki→`HydraFlowConfig.repo_wiki_path`, arch→`DiagramLoop.path_specs`, pricing→`src/assets/model_pricing.json`, ul→`docs/wiki/terms/`. Collect into `MAINTENANCE_WRITE_SCOPES` in `src/factory_maintenance.py`. Add a drift pin test that fails when a loop's `path_specs` move without updating the table.

**Why:** Hardcoded scope tables silently rot when loop definitions change, reopening exclusion bypasses.
