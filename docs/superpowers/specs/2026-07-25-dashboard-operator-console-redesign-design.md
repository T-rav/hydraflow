# Dashboard Operator Console — Redesign Design

**Status:** Draft (brainstormed 2026-07-25)
**Scope:** Redesign the HydraFlow web dashboard (`src/ui`) into a pipeline-centric **operator console**, in two sequenced phases — information design first, visual-system polish second.

---

## 1. Context & Problem

The current dashboard is a three-column layout (`Workers` rail · tabbed work view · `Event Log` rail) under a header, built from ~35 React components with tab-based navigation. An audit of the code and the running dashboard surfaced these problems, in priority order:

1. **The Event Log is a raw firehose** occupying a full third of the screen. It renders *every* internal event as truncated raw JSON (`pipeline stats{"timestamp":"…","stages":{"triage":{"queued":0,`), with heavy repetition (a `pipeline stats` heartbeat every ~5s; `transcript line#10493` repeated 11× in a row) and no severity/grouping. Signal — `Loop adr_drift_resolver crashed`, `system alert`, `review update PR #10528 → done` — is buried in noise. There is even a `transcript line#undefined` rendering bug. It reads like a debug console, not a human activity feed.
2. **Flat information hierarchy / no focal point.** Everything is similar-weight monospace; nothing answers "what needs *me* right now?" (HITL, failures) versus "what is merely happening."
3. **Density imbalance + bare empty states.** When idle, the `Workers` and center panes sit empty ("Waiting for issues…") while the log overwhelms; the layout does not rebalance and empty states offer no polish or guidance.
4. **Inline-style sprawl.** 37 components style inline rather than through the token system (CSS custom properties in `index.html` + a thin `theme.js`). This is the root of visual inconsistency and why the UI is hard to restyle cohesively.
5. **Performance.** The event log is not virtualized; the DOM grows unbounded (heavy enough to stall a full-page screenshot) and will degrade under real load.

## 2. Goals & Non-Goals

**Primary framing:** an **operator's view** — the person running/watching the factory. Optimize for "what is the factory doing, what needs me, let me watch it work."

**Goals**
- **G1 — Pipeline-centric focal point.** The pipeline (Triage → Plan → Build → Review → HITL → Merged) is the hero; attention rides on the stages.
- **G2 — Tame the firehose.** Replace the raw event log with (a) a formatted **per-item live transcript** in the detail pane and (b) a demoted, grouped/filterable **global activity drawer**.
- **G3 — Watch items work.** First-class live transcript per active item, with a **focus-one** default and an **all-active** tiled mode.
- **G4 — Vitals at a glance.** A compact vitals panel replaces scattered `loop crashed` / `system alert` / credit lines with a clean health readout.
- **G5 — Multi-repo.** An "All repos" overview + header switcher + drill-down (`All repos → repo → stage → item → transcript`).
- **G6 — Modern-product visual system.** Evolve the dark terminal aesthetic into a cleaner, modern dashboard: refined sans typography for chrome, mono reserved for data/streams, real spacing/color rhythm, cards, deliberate empty/loading states. Kill the inline-style sprawl by moving to a token-backed style layer.

**Sequencing:** **Phase 1 = information design** (G1–G5, structure + interactions). **Phase 2 = visual system** (G6). Structure is validated before it is painted.

**Non-Goals (YAGNI)**
- No framework change (stays React + Vite).
- No new heavy dependencies or a full component-library adoption; a lightweight internal token/primitive layer is enough.
- No backend/API redesign — consume the existing WebSocket event stream and REST endpoints as-is (adapt shapes in the UI).
- No auth/multi-user/roles work.
- Not a rewrite of every panel — panels not on the operator path (e.g. deep settings, bootstrap wizard) are reused as-is and only restyled in Phase 2.

## 3. Information Architecture & Navigation Model

A single drill hierarchy, each level a click in, breadcrumb a click out:

```
All repos  →  <repo> console  →  <stage>  →  <item>  →  live transcript (Transcript / Diff / PR / Timeline)
```

- **All repos** — portfolio overview (§6). Entry screen when >1 repo is registered.
- **Repo console** — the pipeline-centric operator view (§4) for one repo.
- **Stage** — clicking a pipeline stage focuses the detail pane on that stage's items.
- **Item** — clicking an active/queued item opens its detail (live transcript by default).
- The **breadcrumb** (`‹ All repos › hydraflow ▾ › Build › #10516`) reflects the current depth; every segment is a link. The `hydraflow ▾` switcher jumps sideways to another repo **without changing depth**.
- Depth is URL-addressable (`?repo=…&stage=…&item=…`) so views are shareable/bookmarkable and survive reload (extends the existing `_initialTabFromUrl` pattern).

## 4. The Operator Console (single repo)

Vertical stack; the header and pipeline are always visible, the detail pane is context-sensitive.

### 4.1 Header bar
- Logo + **breadcrumb/repo switcher**.
- **Run-state pill** (Running / Paused / Stopping) — reflects orchestrator status; the credit-pause reason surfaces here (e.g. "Paused — credits reset Jul 29").
- **Aggregate vitals** cluster (Building N/M, Merged today, Loops healthy).
- **Controls** (Start / Stop / Clear) — reuse the existing control endpoints (`PipelineControlPanel`).

### 4.2 Pipeline hero
- Six stage tiles: **Triage · Plan · Build · Review · HITL · Merged**, driven by the existing `queue update` / `pipeline stats` events (stage counts + slot usage, e.g. `Build 2/5`).
- Each tile shows: stage name, count (and slots where relevant), and the **live items** in it as issue chips with a status dot.
- **Attention rides on the tile**: an amber/red corner badge for HITL depth and for failed/stuck items (e.g. HITL `4`). This is the primary focal signal (G1).
- Clicking a tile selects the stage; clicking a chip selects the item.

### 4.3 Detail pane (context-sensitive) — the heart of the redesign
- **Stage selected → item list.** The stage's items with per-item quick actions. For HITL: `Approve` / `Skip` / comment (reuse `HITLTable` / `useHITLCorrection`). For Review: PR + checks summary.
- **Item selected → live workspace.** Header (`#id · title · worker · elapsed · ● LIVE`) + sub-tabs:
  - **Transcript** (default) — the **formatted** live stream: `read / edit / run / pass / agent` lines with timestamps and a live cursor, replacing today's raw `transcript line#…` wall. Sourced from the same `transcript line` + `agent activity` events, parsed into structured rows (extend `StreamView` / `useTimeline`).
  - **Diff** — the item's changed files (`+/−`).
  - **PR** — PR status + checks.
  - **Timeline** — the item's stage history (reuse `useTimeline`).
- **Focus vs. All-active toggle** (in the detail header). `Focus` = one item full-height. `All active` = a responsive grid of tiles, one per building item, each streaming a compact live transcript (replaces today's `Workers` rail as the "see everything at once" view). Tiles reflow as items enter/leave Build.

### 4.4 Vitals card (side of detail)
Compact, scannable health readout, per repo: factory run-state, loops healthy (`18/19`), recently restarted loops (the tamed `Loop … crashed` events), credit state, `main ↔ staging` sync. Rows are color-coded (ok/warn/bad). This absorbs the `system alert` and `worker_status` signal that currently scrolls past in the log.

### 4.5 Global activity drawer (demoted)
A collapsed strip pinned to the bottom: an uppercase `Activity` label, the single latest line, filter chips (`all · errors · merges · hitl`), and a "N new" counter. Expanding it reveals the full stream — but **grouped and deduped** (collapse runs of identical heartbeats; roll up repeated `transcript line` into the item), **filterable by severity/type**, and **virtualized**. Default collapsed. This is where power users go for the raw firehose; it never dominates the screen again.

## 5. Empty & transitional states
- **Idle repo** — the pipeline shows zeros with a calm "Factory idle — nothing in flight" state, not a bare "Waiting for issues…". Controls to start remain obvious.
- **Paused (credit)** — the run-state pill explains why and when it resumes; the console stays fully navigable (history/vitals readable).
- **Socket disconnected** — a non-blocking banner + last-known state retained (extend `useHydraFlowSocket`); reconnect is automatic.
- **Loading** — skeletons in the pipeline/detail, not layout jumps.

## 6. Multi-repo

- **All repos overview** — one row per registered repo: status dot (green/amber/red), name + slug, a **mini pipeline** (per-stage counts), a **"Needs you"** attention badge, **health** (loops up/down), and last-activity. Rows are clickable → that repo's console. Header shows **aggregate vitals** across repos. `+ Add repo` opens the existing `RegisterRepoDialog`.
- **Header switcher** — dropdown of repos to jump directly / sideways.
- Reuse existing multi-repo plumbing (`RepoSelector`, `GitHubRepoPicker`, `ProjectView`, `RegisterRepoDialog`) and the scoping from `2026-06-06-multi-repo-dashboard-scoping-design.md`; this redesign changes the *presentation* (portfolio + drill), not the repo model.
- Single-repo installs skip the overview and land directly in the one repo's console (switcher hidden).

## 7. Visual Design System (Phase 2)

- **Tokens as the single source of truth.** Consolidate color/space/type/radius/shadow into design tokens (extend `theme.js` + the `:root` custom properties) and a small set of **style primitives / styled helpers**. **Migrate the 37 inline-styled components off `style={{…}}` onto tokens/primitives** — this is the core of "keep it clean" and what makes the modern-product look consistent.
- **Type:** refined sans for chrome/labels; **monospace reserved** for data, ids, and transcript streams (intentional, not everywhere).
- **Surface & rhythm:** layered dark surfaces (bg / card / card-elevated), consistent 4px-based spacing, rounded cards, restrained borders, one accent (blue) + semantic colors (amber attention, green ok, red fail, purple edit).
- **Motion:** subtle, purposeful — live pulse, stream cursor, drawer expand, tile reflow. No gratuitous animation.
- **Light/dark:** dark-first; keep the light path working via tokens (don't hardcode dark values).

## 8. Architecture & Integration

**Reuse, don't rewrite.** Map the design onto existing building blocks:

- **Data:** the existing WebSocket (`useHydraFlowSocket`) already carries the needed events — `queue update`, `pipeline stats` (stage counts), `transcript line` + `agent activity` (per-item stream), `worker_status`, `diagnostic update`, `review update`, `system alert`, `epic progress`, `merge update`. No new backend contract; the UI **adapts** these into: pipeline model, per-item transcript model, vitals model, and the activity feed.
- **New/edited units (each with one clear job):**
  - `OperatorConsole` — the repo-level shell (header + pipeline + detail + vitals + drawer); owns selection state (stage/item/mode) and URL sync.
  - `PipelineRail` — stage tiles from the pipeline model; emits stage/item selection.
  - `ItemWorkspace` — the item detail with Transcript/Diff/PR/Timeline tabs; **refactor `StreamView`/`useTimeline`** to feed a *formatted* transcript instead of raw lines.
  - `ActiveGrid` — the all-active tiled mode.
  - `VitalsCard` — health model from `worker_status`/`system alert`/status events.
  - `ActivityDrawer` — grouped/deduped/virtualized global feed (replaces `EventLog`); a `useActivityFeed` hook does the grouping/dedup.
  - `RepoOverview` + `RepoSwitcher` — portfolio + jump (wrap existing `RepoSelector`/`ProjectView`).
  - `tokens`/primitives — the Phase-2 style layer.
- **Retire/absorb:** `EventLog` (→ `ActivityDrawer`), the always-on `Workers` rail (→ `ActiveGrid` "all-active" mode), the top-level tab bar (→ pipeline + drill nav).

## 9. Phasing & Build Sequence

**Phase 1 — Information design (structure + interactions), token-agnostic styling ok:**
1. `OperatorConsole` shell + URL-addressable selection + breadcrumb.
2. `PipelineRail` from the live pipeline/queue model, with attention badges.
3. `ItemWorkspace` with the **formatted** live transcript (the biggest single win); Diff/PR/Timeline tabs.
4. `Focus` / `ActiveGrid` toggle.
5. `VitalsCard`.
6. `ActivityDrawer` — grouping/dedup/virtualization/filters (fixes the firehose + perf).
7. `RepoOverview` + `RepoSwitcher` + drill/breadcrumb wiring.
8. Empty/paused/disconnected/loading states.

**Phase 2 — Visual system:**
9. Token layer + primitives; migrate components off inline styles.
10. Type/surface/spacing/motion polish; light/dark via tokens.

Each Phase-1 item is independently shippable and testable behind the existing dashboard until parity is reached.

## 10. Testing

- **Component/unit (vitest + Testing Library):** pipeline model → stage tiles + badges; transcript parser (raw events → formatted rows, incl. the `#undefined` bug); activity feed grouping/dedup; selection/URL state; focus↔all-active; multi-repo overview rows + drill; empty/paused/disconnected states. Follow existing patterns in `src/ui/src/components/__tests__` and `hooks/__tests__`.
- **Interaction:** breadcrumb pop-up-levels, stage→item selection, switcher sideways jump.
- **Perf guard:** activity feed stays virtualized/bounded under a synthetic high-rate stream (the current pain point; ties to issue #10508's contention work).
- Reuse `run-vitest.cjs` (the CI Dashboard Build lane) as the gate.

## 11. Risks & Open Questions

- **Transcript parsing fidelity** — the formatted stream must not drop information the raw log had; keep a "raw" escape hatch (per-item raw toggle) for debugging.
- **Event volume** — grouping/dedup rules need tuning so nothing important is collapsed away (errors/HITL never deduped).
- **Parity cutover** — build the new console alongside the current UI and switch once the operator path is at parity, rather than a big-bang replacement.
- **Open:** exact stage set / labels for the pipeline hero (confirm against the canonical label state machine, ADR-0002); whether `Outcomes`/`Atlas`/`System` tabs become drill destinations or stay as separate top-level areas reachable from the console.
