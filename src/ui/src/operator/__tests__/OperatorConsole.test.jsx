import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
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

  it('renders all five layout slots', () => {
    render(<OperatorConsoleView socket={makeSocket()} />)
    expect(screen.getByTestId('operator-header-slot')).toBeInTheDocument()
    expect(screen.getByTestId('operator-pipeline-slot')).toBeInTheDocument()
    expect(screen.getByTestId('operator-detail-slot')).toBeInTheDocument()
    expect(screen.getByTestId('operator-vitals-slot')).toBeInTheDocument()
    expect(screen.getByTestId('operator-drawer-slot')).toBeInTheDocument()
  })

  it('mounts the real ConsoleHeader in the header slot (Task 8)', () => {
    render(<OperatorConsoleView socket={makeSocket()} />)
    expect(screen.getByTestId('console-header')).toBeInTheDocument()
  })

  it('renders placeholder children for the not-yet-built components', () => {
    render(<OperatorConsoleView socket={makeSocket()} />)
    expect(screen.getByTestId('item-workspace-placeholder')).toBeInTheDocument()
  })

  it('mounts the real ActivityDrawer in the drawer slot (Task 7)', () => {
    render(<OperatorConsoleView socket={makeSocket()} />)
    expect(screen.getByTestId('activity-drawer')).toBeInTheDocument()
  })

  it('wires the real VitalsCard into the vitals slot (Task 6)', () => {
    render(<OperatorConsoleView socket={makeSocket()} />)
    expect(screen.getByTestId('vitals-card')).toBeInTheDocument()
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
})
