import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { OperatorConsoleView } from '../OperatorConsole'

// Task 2 ships only the shell: it renders its five slots (header / pipeline /
// detail / vitals / drawer) with placeholder children (the real components land
// in Tasks 3-9) and wires the Task-1 adapters against an injected socket. The
// injected `socket` prop is the seam that keeps the presentational shell
// testable without spinning up a live HydraFlowProvider/WebSocket.

// A fixture shaped like the HydraFlowContext value: events (newest-first) plus
// the dedicated pipeline slices the reducer maintains.
function makeSocket(overrides = {}) {
  return {
    events: [
      {
        type: 'transcript_line',
        timestamp: '2026-07-26T12:00:02Z',
        id: 3,
        data: { issue: 42, line: 'running tests' },
      },
      {
        type: 'orchestrator_status',
        timestamp: '2026-07-26T12:00:01Z',
        id: 2,
        data: { status: 'running' },
      },
    ],
    pipelineIssues: {
      triage: [{ issue_number: 42, title: 'Fix login', status: 'active' }],
      plan: [],
      implement: [],
      review: [],
      hitl: [],
      merged: [],
    },
    pipelineStats: null,
    ...overrides,
  }
}

describe('OperatorConsoleView — shell', () => {
  let originalHref

  beforeEach(() => {
    originalHref = window.location.href
    window.history.replaceState({}, '', '/')
  })

  afterEach(() => {
    window.history.replaceState({}, '', originalHref)
  })

  it('renders the console container without crashing given a socket fixture', () => {
    render(<OperatorConsoleView socket={makeSocket()} />)
    expect(screen.getByTestId('operator-console')).toBeInTheDocument()
  })

  it('renders the four layout slots (the bottom drawer was removed, #11)', () => {
    render(<OperatorConsoleView socket={makeSocket()} />)
    expect(screen.getByTestId('operator-header-slot')).toBeInTheDocument()
    expect(screen.getByTestId('operator-pipeline-slot')).toBeInTheDocument()
    expect(screen.getByTestId('operator-detail-slot')).toBeInTheDocument()
    expect(screen.getByTestId('operator-vitals-slot')).toBeInTheDocument()
    // The Activity drawer slot is gone (#11) — its vertical space is reclaimed.
    expect(screen.queryByTestId('operator-drawer-slot')).toBeNull()
  })

  it('mounts the real ConsoleHeader in the header slot (Task 8)', () => {
    render(<OperatorConsoleView socket={makeSocket()} />)
    expect(screen.getByTestId('console-header')).toBeInTheDocument()
  })

  it('mounts the real ItemWorkspace in the detail slot (Task 4)', () => {
    render(<OperatorConsoleView socket={makeSocket()} />)
    expect(screen.getByTestId('item-workspace')).toBeInTheDocument()
  })

  it('no longer mounts the ActivityDrawer (removed, #11)', () => {
    render(<OperatorConsoleView socket={makeSocket()} />)
    expect(screen.queryByTestId('activity-drawer')).toBeNull()
  })

  it('wires the real VitalsCard into the vitals slot (Task 6)', () => {
    render(<OperatorConsoleView socket={makeSocket()} />)
    expect(screen.getByTestId('vitals-card')).toBeInTheDocument()
  })

  it('mounts the LoopsPanel in the vitals slot (all-loops quick view)', () => {
    render(<OperatorConsoleView socket={makeSocket({
      backgroundWorkers: [
        { name: 'ci_monitor', status: 'ok', last_run: '2026-07-26T12:00:00Z', details: { filed: 0 }, enabled: true, interval_seconds: 300 },
      ],
    })} />)
    const vitalsSlot = screen.getByTestId('operator-vitals-slot')
    expect(vitalsSlot).toContainElement(screen.getByTestId('loops-panel'))
    // Categories start collapsed; the ci_monitor loop flowing through groups it
    // under its Repo Health category header (rows appear once expanded).
    expect(screen.getByTestId('loops-category-toggle-repo_health')).toBeInTheDocument()
  })

  it('mounts the phase timeline in the reclaimed bottom slot (feat/operator-timeline)', () => {
    render(<OperatorConsoleView socket={makeSocket()} />)
    const slot = screen.getByTestId('operator-timeline-slot')
    expect(slot).toBeInTheDocument()
    // The timeline panel lives in the full-width bottom slot (PR2 reclaimed the
    // old drawer space); with no phase_change in the fixture it renders empty.
    expect(slot).toContainElement(screen.getByTestId('timeline-panel'))
  })

  it('folds phase_change events into the bottom timeline (a phase container renders)', () => {
    const socket = makeSocket({
      // Newest-first, as the reducer stores: a PR opened during the Build phase.
      events: [
        { type: 'pr_created', timestamp: '2026-07-26T12:10:00Z', id: 6, data: { pr: 820, issue: 42, url: 'https://gh/pull/820' } },
        { type: 'phase_change', timestamp: '2026-07-26T12:05:00Z', id: 5, data: { phase: 'implement', issue: 42 } },
      ],
    })
    render(<OperatorConsoleView socket={socket} now={Date.parse('2026-07-26T12:12:00Z')} />)
    expect(screen.getByTestId('timeline-phase-implement')).toBeInTheDocument()
    // The pr_created folds inside the phase as a diff row.
    expect(screen.getByTestId('timeline-diff-6')).toBeInTheDocument()
  })

  it('mounts the real PipelineRail in the pipeline slot (Task 3)', () => {
    render(<OperatorConsoleView socket={makeSocket()} />)
    expect(screen.getByTestId('pipeline-rail')).toBeInTheDocument()
  })

  it('wires the pipeline adapter — the rail reflects the six stages', () => {
    const { container } = render(<OperatorConsoleView socket={makeSocket()} />)
    expect(container.querySelectorAll('[data-testid^="stage-tile-"]')).toHaveLength(6)
  })

  it('reflects URL-initialised selection in the header breadcrumb', () => {
    window.history.replaceState({}, '', '/?repo=acme%2Fweb&stage=plan')
    render(<OperatorConsoleView socket={makeSocket()} />)
    // root + repo + stage = depth 3
    expect(screen.getByTestId('console-header')).toHaveTextContent('acme/web')
    expect(screen.getByTestId('console-header')).toHaveTextContent('Plan')
  })

  it('does not crash on an empty socket (no events, no pipeline slices)', () => {
    const { container } = render(<OperatorConsoleView socket={{}} />)
    expect(screen.getByTestId('operator-console')).toBeInTheDocument()
    // The rail always renders the six canonical stages, even with no data.
    expect(container.querySelectorAll('[data-testid^="stage-tile-"]')).toHaveLength(6)
  })

  // --- #12: header shows factory runtime, not a redundant loop count ----------

  it('shows the factory runtime in the header when a session start is known', () => {
    const socket = makeSocket({
      sessions: [{ id: 'acme-20260727T100000', status: 'active', started_at: '2026-07-27T10:00:00Z' }],
      currentSessionId: 'acme-20260727T100000',
    })
    render(<OperatorConsoleView socket={socket} now={Date.parse('2026-07-27T12:14:00Z')} />)
    expect(screen.getByTestId('header-uptime')).toHaveTextContent('2h14m')
    // The old redundant loop-health count is gone from the header.
    expect(screen.queryByTestId('console-header-loops')).toBeNull()
  })

  it('renders no runtime readout when no start signal is available', () => {
    render(<OperatorConsoleView socket={makeSocket()} />)
    expect(screen.queryByTestId('header-uptime')).toBeNull()
  })

  // --- #8: focus mode spans the full detail width -----------------------------

  it('spans the detail slot full width in focus mode', () => {
    render(<OperatorConsoleView socket={makeSocket()} />)
    // Default mode is focus with an active item → full-width detail.
    expect(screen.getByTestId('operator-detail-slot')).toHaveAttribute('data-fullwidth', 'true')
  })

  it('does not span full width in all-active mode (vitals keeps its column)', () => {
    render(<OperatorConsoleView socket={makeSocket()} />)
    fireEvent.click(screen.getByTestId('mode-toggle-all-active'))
    expect(screen.getByTestId('operator-detail-slot')).toHaveAttribute('data-fullwidth', 'false')
  })

  // --- Task 5: focus <-> all-active mode toggle -------------------------------

  it('renders the mode toggle, defaulting to focus (single ItemWorkspace)', () => {
    render(<OperatorConsoleView socket={makeSocket()} />)
    expect(screen.getByTestId('mode-toggle')).toBeInTheDocument()
    expect(screen.getByTestId('mode-toggle-focus')).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByTestId('mode-toggle-all-active')).toHaveAttribute('aria-pressed', 'false')
    // Focus path: the single ItemWorkspace is in the detail slot; no grid.
    expect(screen.getByTestId('item-workspace')).toBeInTheDocument()
    expect(screen.queryByTestId('active-grid')).toBeNull()
  })

  it('toggles to all-active — swaps ItemWorkspace for ActiveGrid and persists mode to the URL', () => {
    render(<OperatorConsoleView socket={makeSocket()} />)
    fireEvent.click(screen.getByTestId('mode-toggle-all-active'))

    expect(screen.getByTestId('active-grid')).toBeInTheDocument()
    expect(screen.queryByTestId('item-workspace')).toBeNull()
    expect(screen.getByTestId('mode-toggle-all-active')).toHaveAttribute('aria-pressed', 'true')
    // Selection is mirrored into the query string (spec §3).
    expect(new URLSearchParams(window.location.search).get('mode')).toBe('all-active')
  })

  it('toggles back to focus — restores ItemWorkspace and clears mode from the URL', () => {
    render(<OperatorConsoleView socket={makeSocket()} />)
    fireEvent.click(screen.getByTestId('mode-toggle-all-active'))
    fireEvent.click(screen.getByTestId('mode-toggle-focus'))

    expect(screen.getByTestId('item-workspace')).toBeInTheDocument()
    expect(screen.queryByTestId('active-grid')).toBeNull()
    // Default mode is written as a clean URL (no ?mode).
    expect(new URLSearchParams(window.location.search).get('mode')).toBeNull()
  })

  it('restores all-active mode from the URL on load', () => {
    window.history.replaceState({}, '', '/?mode=all-active')
    render(<OperatorConsoleView socket={makeSocket({
      pipelineIssues: {
        triage: [], plan: [],
        implement: [{ issue_number: 42, title: 'Fix login', status: 'active' }],
        review: [], hitl: [], merged: [],
      },
    })} />)
    expect(screen.getByTestId('active-grid')).toBeInTheDocument()
    expect(screen.getByTestId('active-tile-42')).toBeInTheDocument()
    expect(screen.queryByTestId('item-workspace')).toBeNull()
  })

  // --- Task 9: multi-repo overview + switcher drill ---------------------------

  // A multi-repo aggregate fixture: two supervised repos + a repo-tagged pipeline
  // snapshot, shaped like the repo=__all__ context value.
  function makeMultiRepoSocket(overrides = {}) {
    return makeSocket({
      supervisedRepos: [
        { slug: 'acme/app', running: true },
        { slug: 'acme/lib', running: false },
      ],
      runtimes: [{ slug: 'acme/app', running: true }],
      pipelineIssues: {
        triage: [{ issue_number: 1, title: 'T', status: 'queued', repo: 'acme-app' }],
        plan: [], implement: [], review: [],
        hitl: [{ issue_number: 9, title: 'Stuck', status: 'hitl', repo: 'acme-lib' }],
        merged: [],
      },
      ...overrides,
    })
  }

  it('shows the RepoOverview portfolio and the RepoSwitcher for a multi-repo install with no repo selected', () => {
    render(<OperatorConsoleView socket={makeMultiRepoSocket()} />)
    expect(screen.getByTestId('repo-overview')).toBeInTheDocument()
    expect(screen.getByTestId('repo-row-acme/app')).toBeInTheDocument()
    expect(screen.getByTestId('repo-row-acme/lib')).toBeInTheDocument()
    expect(screen.getByTestId('repo-switcher-trigger')).toBeInTheDocument()
    // The overview replaces the pipeline hero until a repo is drilled into.
    expect(screen.queryByTestId('pipeline-rail')).toBeNull()
  })

  it('drills to the pipeline (and hides the overview) once a repo is selected', () => {
    window.history.replaceState({}, '', '/?repo=acme%2Fapp')
    render(<OperatorConsoleView socket={makeMultiRepoSocket()} />)
    expect(screen.queryByTestId('repo-overview')).toBeNull()
    expect(screen.getByTestId('pipeline-rail')).toBeInTheDocument()
    // The switcher stays available for a sideways jump.
    expect(screen.getByTestId('repo-switcher-trigger')).toBeInTheDocument()
  })

  it('shows the pipeline directly (no overview / switcher) for a single-repo install', () => {
    render(<OperatorConsoleView socket={makeMultiRepoSocket({
      supervisedRepos: [{ slug: 'acme/app', running: true }],
    })} />)
    expect(screen.queryByTestId('repo-overview')).toBeNull()
    expect(screen.queryByTestId('repo-switcher-trigger')).toBeNull()
    expect(screen.getByTestId('pipeline-rail')).toBeInTheDocument()
  })
})
