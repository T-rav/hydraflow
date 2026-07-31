---
id: 2211
topic: testing
source_issue: 10897
source_phase: plan
created_at: 2026-07-31T12:53:03.086146+00:00
status: superseded
corroborations: 1
superseded_by: 2355
---

# Derive maintenance write scopes from live loop definitions

Read each loop's write scope from its canonical source: wiki→`HydraFlowConfig.repo_wiki_path`, arch→`DiagramLoop.path_specs`, pricing→`src/assets/model_pricing.json`, ul→`docs/wiki/terms/`. Collect into `MAINTENANCE_WRITE_SCOPES` in `src/factory_maintenance.py`. Add a drift pin test that fails when a loop's `path_specs` move without updating the table. **Why:** Hardcoded scope tables silently rot when loop definitions change, reopening exclusion bypasses.
