---
id: 2355
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:40:37.116818+00:00
status: superseded
corroborations: 1
supersedes: 2211
superseded_by: 2544
---

# Derive maintenance write scopes from live loop definitions

Read each loop's write scope from its canonical source: wiki→`HydraFlowConfig.repo_wiki_path`, arch→`DiagramLoop.path_specs`, pricing→`src/assets/model_pricing.json`, ul→`docs/wiki/terms/`. Collect into `MAINTENANCE_WRITE_SCOPES` in `src/factory_maintenance.py`. Add a drift pin test that fails when a loop's `path_specs` move without updating the table.

**Why:** Hardcoded scope tables silently rot when loop definitions change, reopening exclusion bypasses.
