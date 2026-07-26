# Dashboard Operator Console Redesign — Implementation Plan

> **For agentic workers:** each Task below is a self-contained, TDD, independently-shippable unit intended to be built as its own factory ticket (child of the epic). Build behind the existing dashboard until Phase-1 parity, then cut over. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace the current three-column HydraFlow dashboard with a pipeline-centric **operator console** — pipeline hero + attention, per-item formatted live transcript, tamed/grouped activity, vitals, and a multi-repo overview — then a token-backed visual-system pass.

**Architecture:** New React feature under `src/ui/src/operator/` that consumes the *existing* WebSocket event stream (`useHydraFlowSocket`) and REST endpoints — no backend contract change. Presentation-layer adapters turn the raw event stream into four view models (pipeline, per-item transcript, vitals, activity feed). Built alongside the current UI behind a flag; cut over at parity. Phase 2 introduces a token/primitive style layer and migrates components off inline styles.

**Tech Stack:** React 18 + Vite, vitest + @testing-library/react (gate: `src/ui/scripts/run-vitest.cjs`), existing WebSocket/REST hooks. No new runtime deps.

## Global Constraints

- No framework change; no new runtime dependencies (dev-only tooling ok). — verbatim from spec §2.
- No backend/API changes — consume existing WS events (`queue update`, `pipeline stats`, `transcript line`, `agent activity`, `worker_status`, `diagnostic update`, `review update`, `system alert`, `epic progress`, `merge update`) and existing REST/control endpoints. — spec §2, §8.
- Reuse, don't rewrite: extend `StreamView`, `useTimeline`, `useHydraFlowSocket`, `HITLTable`/`useHITLCorrection`, `PipelineControlPanel`, `RepoSelector`/`ProjectView`/`RegisterRepoDialog`. — spec §8.
- Tests are the gate: every task ships vitest coverage; CI lane = `run-vitest.cjs`. Bug-fix behavior (e.g. `transcript line#undefined`) ships a regression test. — spec §10.
- Errors/HITL are NEVER deduped/collapsed in the activity feed. — spec §11.
- Dark-first but no hardcoded dark values in Phase-2 — everything through tokens so the light path keeps working. — spec §7.
- New view is URL-addressable (`?repo=&stage=&item=&mode=`), extending the existing `_initialTabFromUrl` pattern. — spec §3.

---

## Phase 1 — Information design (structure + interactions)

### Task 1: View-model adapters (pure, tested)
**Files:** Create `src/ui/src/operator/model/pipeline.js`, `.../model/transcript.js`, `.../model/vitals.js`, `.../model/activity.js`; Test `src/ui/src/operator/model/__tests__/*.test.js`.
**Interfaces — Produces:**
- `toPipeline(events|snapshot) -> { stages: [{key,label,count,slots,items:[{id,title,status}], attention:{hitl,failed}}] }`
- `toTranscript(events, issueId) -> [{ts, kind:'read'|'edit'|'run'|'pass'|'fail'|'agent', text, meta}]` (parses `transcript line` + `agent activity`; **drops/repairs `#undefined` ids**).
- `toVitals(events) -> { factory, loopsHealthy:{ok,total}, restarts:[{loop,count}], credits, mainStagingSync }`
- `toActivityFeed(events) -> [{ts, type, severity, summary, groupKey, count}]` — collapses runs of identical heartbeats and repeated `transcript line` into one row with `count`; **never groups error/hitl/alert**.
- [ ] Write failing tests: a raw event fixture (reuse the shapes seen in the live log) → each adapter's expected view model; include the `transcript line#undefined` repair case and the "11 identical transcript lines collapse to count:11" case, and "two errors never merge".
- [ ] Verify fail → implement pure adapters → verify pass → commit.

### Task 2: `OperatorConsole` shell + selection + URL sync
**Files:** Create `src/ui/src/operator/OperatorConsole.jsx`, `.../useOperatorSelection.js`; Test `__tests__/OperatorConsole.test.jsx`, `__tests__/useOperatorSelection.test.js`.
**Interfaces — Consumes:** adapters (Task 1), `useHydraFlowSocket`. **Produces:** `useOperatorSelection() -> {repo, stage, item, mode, select(...), breadcrumb}` synced to the URL query.
- [ ] Failing tests: selecting a stage/item updates state + URL; reload from URL restores depth; breadcrumb array reflects depth.
- [ ] Implement shell (header slot, pipeline slot, detail slot, vitals slot, drawer slot) + selection hook → pass → commit. (Renders placeholders for child components; those land in later tasks.)

### Task 3: `PipelineRail` (the hero)
**Files:** Create `src/ui/src/operator/PipelineRail.jsx`; Test `__tests__/PipelineRail.test.jsx`.
**Interfaces — Consumes:** `toPipeline(...)`, `useOperatorSelection`. **Produces:** stage tiles emitting `select('stage', key)` / `select('item', id)`.
- [ ] Failing tests: renders 6 stages with counts/slots from a pipeline VM; HITL tile shows an attention badge = hitl depth; a failed item shows a red badge; clicking a tile/chip calls select with the right args.
- [ ] Implement → pass → commit.

### Task 4: `ItemWorkspace` + formatted live transcript
**Files:** Create `src/ui/src/operator/ItemWorkspace.jsx`, `.../TranscriptStream.jsx`; Modify `src/ui/src/components/StreamView.jsx` (extract/reuse rendering), `src/ui/src/hooks/useTimeline.js` (feed formatted rows); Test `__tests__/ItemWorkspace.test.jsx`, `__tests__/TranscriptStream.test.jsx`.
**Interfaces — Consumes:** `toTranscript(...)`, item selection. **Produces:** tabbed workspace (`Transcript` default | `Diff` | `PR` | `Timeline`) with a live-updating formatted stream + a "raw" escape-hatch toggle.
- [ ] Failing tests: given a transcript VM, renders formatted rows (read/edit/run/pass/agent) with timestamps, a live indicator when the item is active, and appends on new events; raw toggle shows unparsed lines; `#undefined` never renders as a header.
- [ ] Implement → pass → commit.

### Task 5: Focus ↔ All-active modes (`ActiveGrid`)
**Files:** Create `src/ui/src/operator/ActiveGrid.jsx`; Modify `OperatorConsole.jsx` (mode toggle); Test `__tests__/ActiveGrid.test.jsx`.
**Interfaces — Consumes:** pipeline VM (building items) + `toTranscript` per item, `mode` from selection. **Produces:** grid of compact live transcripts; `Focus` shows one `ItemWorkspace`.
- [ ] Failing tests: `mode='all-active'` renders one tile per building item, each streaming; tiles add/remove as the building set changes; toggle switches focus/all-active and persists to URL.
- [ ] Implement → pass → commit.

### Task 6: `VitalsCard`
**Files:** Create `src/ui/src/operator/VitalsCard.jsx`; Test `__tests__/VitalsCard.test.jsx`.
**Interfaces — Consumes:** `toVitals(...)`. **Produces:** color-coded vitals rows (factory state, loops ok/total, restarts, credits, main↔staging).
- [ ] Failing tests: renders each vital with correct ok/warn/bad class from a vitals VM; a restarted loop shows bad; paused factory shows warn with reason.
- [ ] Implement → pass → commit.

### Task 7: `ActivityDrawer` (demote + group + virtualize)
**Files:** Create `src/ui/src/operator/ActivityDrawer.jsx`, `.../useActivityFeed.js`; Remove-from-path `src/ui/src/components/EventLog.jsx` (keep file until cutover); Test `__tests__/ActivityDrawer.test.jsx`, `__tests__/useActivityFeed.test.js`.
**Interfaces — Consumes:** `toActivityFeed(...)`. **Produces:** collapsed strip (latest line + filter chips `all·errors·merges·hitl` + "N new"); expanded = virtualized grouped list.
- [ ] Failing tests: collapsed shows the latest event; filter chips narrow by type; grouped rows show a count; **error/hitl rows are never grouped**; list virtualizes (only a bounded number of nodes rendered for a large feed).
- [ ] Implement (lightweight windowing; no new dep — slice by scroll) → pass → commit.

### Task 8: Header — run-state, controls, breadcrumb/switcher
**Files:** Create `src/ui/src/operator/ConsoleHeader.jsx`, `.../Breadcrumb.jsx`; Reuse `PipelineControlPanel` control calls; Test `__tests__/ConsoleHeader.test.jsx`, `__tests__/Breadcrumb.test.jsx`.
**Interfaces — Consumes:** vitals/run-state, `useOperatorSelection`. **Produces:** header with run-state pill (+ credit reason), aggregate vitals, Start/Stop/Clear, and a clickable breadcrumb (`‹ All repos › repo ▾ › stage › item`).
- [ ] Failing tests: run-state pill reflects orchestrator status; paused shows credit reason; breadcrumb segments call `select` to pop to that depth; controls invoke the existing endpoints.
- [ ] Implement → pass → commit.

### Task 9: Multi-repo overview + switcher + drill
**Files:** Create `src/ui/src/operator/RepoOverview.jsx`, `.../RepoSwitcher.jsx`; Reuse `RepoSelector`/`ProjectView`/`RegisterRepoDialog`; Test `__tests__/RepoOverview.test.jsx`, `__tests__/RepoSwitcher.test.jsx`.
**Interfaces — Consumes:** per-repo pipeline/vitals VMs. **Produces:** portfolio rows (status dot, name, mini-pipeline, "needs you" badge, health, last-activity) → `select('repo', slug)`; switcher jumps sideways preserving depth; `+ Add repo` opens `RegisterRepoDialog`.
- [ ] Failing tests: a row per repo with mini-pipeline counts + attention badge + health dot; clicking a row selects that repo; switcher preserves stage/item depth; single-repo installs skip the overview.
- [ ] Implement → pass → commit.

### Task 10: States (empty / paused / disconnected / loading) + cutover flag
**Files:** Create `src/ui/src/operator/states/*.jsx`; Modify `src/ui/src/App.jsx` (mount `OperatorConsole` behind a flag, default on once parity), `useHydraFlowSocket` (surface disconnected); Test `__tests__/states.test.jsx`, update `App.test.jsx`.
- [ ] Failing tests: idle repo shows calm idle state (not "Waiting for issues…"); paused shows reason+resume; socket disconnect shows non-blocking banner + retains last state; loading shows skeletons not layout jumps; flag mounts the console.
- [ ] Implement → pass → commit. **End of Phase 1 = operator path at parity; flip the flag.**

## Phase 2 — Visual system

### Task 11: Token + primitive layer
**Files:** Modify `src/ui/src/theme.js` + `index.html` `:root`; Create `src/ui/src/styles/tokens.js`, `.../primitives.jsx` (Surface/Card/Text/Stack/Badge/Button); Test `__tests__/primitives.test.jsx`.
**Interfaces — Produces:** token object (color/space/type/radius/shadow, light+dark) + primitive components consuming only tokens.
- [ ] Failing tests: primitives render token-driven styles; switching theme flips values via tokens (no hardcoded hex).
- [ ] Implement → pass → commit.

### Task 12: Migrate operator components + high-traffic panels off inline styles
**Files:** Modify the `src/ui/src/operator/*` components + the highest-traffic of the 37 inline-styled components (start with those on the operator path); Test: existing component tests stay green + a lint/guard.
- [ ] Add a guard test/lint that fails on new `style={{…}}` in migrated dirs (grandfather the rest). — mirrors the repo's ratchet pattern.
- [ ] Migrate operator components to primitives/tokens; polish type/surface/spacing/motion; verify light+dark via tokens → tests green → commit. (Remaining legacy panels migrate opportunistically; the ratchet prevents backslide.)

---

## Self-Review

- **Spec coverage:** §3 nav → T2/T8/T9; §4.1 header → T8; §4.2 pipeline → T3; §4.3 detail/transcript/tabs/modes → T4/T5; §4.4 vitals → T6; §4.5 drawer → T7; §5 states → T10; §6 multi-repo → T9; §7 visual system → T11/T12; §8 adapters/integration → T1 + per-task reuse notes; §10 testing → per-task; §11 risks (raw escape hatch → T4; never-dedup errors → T1/T7; parity cutover → T10). All sections covered.
- **Placeholder scan:** none — each task names files, interfaces, and concrete test cases.
- **Type consistency:** adapter names (`toPipeline`/`toTranscript`/`toVitals`/`toActivityFeed`) and `useOperatorSelection` shape are referenced consistently by consuming tasks.
