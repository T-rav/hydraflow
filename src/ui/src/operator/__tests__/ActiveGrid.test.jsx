import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'
import { ActiveGrid, buildingItemsOf } from '../ActiveGrid'

// ActiveGrid (epic #10556, Task 5) is the operator console's all-active view: a
// grid of compact live transcripts, one tile per BUILDING item (the pipeline
// VM's Build/`implement` stage). Each tile streams that item's transcript via
// the Task-4 `toTranscript(...)` -> `TranscriptStream` reuse. Tests pass a
// hand-built pipeline VM + raw events so the component is decoupled from the
// adapters (mirrors the ItemWorkspace/OperatorConsole test seams).

// A pipeline VM shaped like `toPipeline(...)` output, parameterised by the set
// of Build-stage items so tests can grow/shrink the building set.
function pipelineWithBuilding(items) {
  return {
    stages: [
      { key: 'triage', label: 'Triage', count: 0, slots: null, items: [], attention: { hitl: 0, failed: 0 } },
      { key: 'plan', label: 'Plan', count: 0, slots: null, items: [], attention: { hitl: 0, failed: 0 } },
      { key: 'implement', label: 'Build', count: items.length, slots: null, items, attention: { hitl: 0, failed: 0 } },
      { key: 'review', label: 'Review', count: 0, slots: null, items: [], attention: { hitl: 0, failed: 0 } },
      { key: 'hitl', label: 'HITL', count: 0, slots: null, items: [], attention: { hitl: 0, failed: 0 } },
      { key: 'merged', label: 'Merged', count: 0, slots: null, items: [], attention: { hitl: 0, failed: 0 } },
    ],
  }
}

// A pipeline VM parameterised by items per workflow stage, so tests can place
// active work in triage/plan/review — not just Build (issue #13).
function pipelineWith({ triage = [], plan = [], implement = [], review = [], hitl = [], merged = [] } = {}) {
  const stage = (key, label, items) => ({ key, label, count: items.length, slots: null, items, attention: { hitl: 0, failed: 0 } })
  return {
    stages: [
      stage('triage', 'Triage', triage),
      stage('plan', 'Plan', plan),
      stage('implement', 'Build', implement),
      stage('review', 'Review', review),
      stage('hitl', 'HITL', hitl),
      stage('merged', 'Merged', merged),
    ],
  }
}

const buildItem = (id, title = `Issue #${id}`) => ({ id, title, status: 'active' })

// Raw WS events shaped like the reducer stores them (as toTranscript consumes).
function eventsFor(...ids) {
  return ids.map((id, i) => ({
    type: 'transcript_line',
    timestamp: `2026-07-26T12:00:0${i}Z`,
    data: { issue: id, line: `working on ${id}` },
  }))
}

// A single transcript_line at a chosen ISO time — pins an item's start-of-
// activity so the running-duration is deterministic against an injected `now`.
function eventAt(id, iso) {
  return { type: 'transcript_line', timestamp: iso, data: { issue: id, line: `working on ${id}` } }
}

describe('buildingItemsOf', () => {
  it('returns the Build (implement) stage items', () => {
    const items = [buildItem(42), buildItem(77)]
    expect(buildingItemsOf(pipelineWithBuilding(items))).toEqual(items)
  })

  it('returns an empty array for a missing / empty pipeline', () => {
    expect(buildingItemsOf(null)).toEqual([])
    expect(buildingItemsOf({})).toEqual([])
    expect(buildingItemsOf({ stages: [] })).toEqual([])
  })
})

describe('ActiveGrid', () => {
  it('renders one tile per building item, each streaming', () => {
    const pipeline = pipelineWithBuilding([buildItem(42, 'Fix login'), buildItem(77, 'Add cache')])
    render(<ActiveGrid pipeline={pipeline} events={eventsFor(42, 77)} />)

    expect(screen.getByTestId('active-grid')).toBeInTheDocument()
    // One tile per building item.
    expect(screen.getByTestId('active-tile-42')).toBeInTheDocument()
    expect(screen.getByTestId('active-tile-77')).toBeInTheDocument()
    // Each tile carries a live transcript stream (streaming).
    expect(screen.getAllByTestId('transcript-stream')).toHaveLength(2)
    // The stage-coloured live dot on each tile replaces the old generic "LIVE"
    // pulse (#17), which is suppressed inside the tile stream.
    expect(screen.getByTestId('active-stage-dot-42')).toBeInTheDocument()
    expect(screen.getByTestId('active-stage-dot-77')).toBeInTheDocument()
    expect(screen.queryByTestId('transcript-live')).toBeNull()
  })

  it('routes each item’s own transcript into its tile', () => {
    const pipeline = pipelineWithBuilding([buildItem(42), buildItem(77)])
    render(<ActiveGrid pipeline={pipeline} events={eventsFor(42, 77)} />)

    const tile42 = screen.getByTestId('active-tile-42')
    const tile77 = screen.getByTestId('active-tile-77')
    expect(within(tile42).getByText(/working on 42/)).toBeInTheDocument()
    expect(within(tile42).queryByText(/working on 77/)).toBeNull()
    expect(within(tile77).getByText(/working on 77/)).toBeInTheDocument()
  })

  it('shows the item id + title in each tile header', () => {
    const pipeline = pipelineWithBuilding([buildItem(42, 'Fix login')])
    render(<ActiveGrid pipeline={pipeline} events={eventsFor(42)} />)
    const header = screen.getByTestId('active-tile-header-42')
    expect(header).toHaveTextContent('#42')
    expect(header).toHaveTextContent('Fix login')
  })

  it('adds and removes tiles as the building set changes', () => {
    const { rerender } = render(
      <ActiveGrid pipeline={pipelineWithBuilding([buildItem(42), buildItem(77)])} events={eventsFor(42, 77)} />,
    )
    expect(screen.getAllByTestId(/^active-tile-\d+$/)).toHaveLength(2)

    // One item finishes building -> its tile disappears.
    rerender(<ActiveGrid pipeline={pipelineWithBuilding([buildItem(42)])} events={eventsFor(42)} />)
    expect(screen.getAllByTestId(/^active-tile-\d+$/)).toHaveLength(1)
    expect(screen.getByTestId('active-tile-42')).toBeInTheDocument()
    expect(screen.queryByTestId('active-tile-77')).toBeNull()

    // Two new items start building -> tiles appear.
    rerender(
      <ActiveGrid
        pipeline={pipelineWithBuilding([buildItem(42), buildItem(88), buildItem(99)])}
        events={eventsFor(42, 88, 99)}
      />,
    )
    expect(screen.getAllByTestId(/^active-tile-\d+$/)).toHaveLength(3)
    expect(screen.getByTestId('active-tile-88')).toBeInTheDocument()
    expect(screen.getByTestId('active-tile-99')).toBeInTheDocument()
  })

  it('shows a calm empty state when nothing is building', () => {
    render(<ActiveGrid pipeline={pipelineWithBuilding([])} events={[]} />)
    expect(screen.getByTestId('active-grid')).toBeInTheDocument()
    expect(screen.getByTestId('active-grid-empty')).toBeInTheDocument()
    expect(screen.queryByTestId(/^active-tile-/)).toBeNull()
  })

  it('renders active items from every workflow stage, not just Build (#13)', () => {
    const pipeline = pipelineWith({
      triage: [buildItem(11, 'Triage me')],
      plan: [buildItem(22, 'Plan me')],
      implement: [buildItem(33, 'Build me')],
      review: [buildItem(44, 'Review me')],
    })
    render(<ActiveGrid pipeline={pipeline} events={eventsFor(11, 22, 33, 44)} />)

    // One tile per active item across triage → plan → build → review.
    expect(screen.getByTestId('active-tile-11')).toBeInTheDocument()
    expect(screen.getByTestId('active-tile-22')).toBeInTheDocument()
    expect(screen.getByTestId('active-tile-33')).toBeInTheDocument()
    expect(screen.getByTestId('active-tile-44')).toBeInTheDocument()
    expect(screen.getAllByTestId(/^active-tile-\d+$/)).toHaveLength(4)
    // Each tile is labelled with the stage it is running in.
    expect(screen.getByTestId('active-stage-11')).toHaveTextContent('Triage')
    expect(screen.getByTestId('active-stage-22')).toHaveTextContent('Plan')
    expect(screen.getByTestId('active-stage-44')).toHaveTextContent('Review')
  })

  it('excludes terminal stages (hitl waits on a human, merged is history)', () => {
    const pipeline = pipelineWith({
      implement: [buildItem(33)],
      hitl: [buildItem(55)],
      merged: [buildItem(66)],
    })
    render(<ActiveGrid pipeline={pipeline} events={eventsFor(33, 55, 66)} />)

    expect(screen.getByTestId('active-tile-33')).toBeInTheDocument()
    expect(screen.queryByTestId('active-tile-55')).toBeNull()
    expect(screen.queryByTestId('active-tile-66')).toBeNull()
  })

  it('shows how long an item has been running, from a fixed now (deterministic) (#7)', () => {
    const pipeline = pipelineWith({ implement: [buildItem(42, 'Fix login')] })
    // Item first seen at 10:00:00Z; the clock is pinned 12 minutes later.
    const events = [eventAt(42, '2026-07-27T10:00:00Z'), eventAt(42, '2026-07-27T10:05:00Z')]
    const now = Date.parse('2026-07-27T10:12:00Z')
    render(<ActiveGrid pipeline={pipeline} events={events} now={now} />)

    expect(screen.getByTestId('active-duration-42')).toHaveTextContent('12m')
  })

  it('formats a multi-hour running duration as `h`+padded minutes', () => {
    const pipeline = pipelineWith({ review: [buildItem(77, 'Long review')] })
    const start = Date.parse('2026-07-27T08:00:00Z')
    const events = [eventAt(77, '2026-07-27T08:00:00Z')]
    const now = start + (64 * 60 * 1000) // 1h04m later
    render(<ActiveGrid pipeline={pipeline} events={events} now={now} />)

    expect(screen.getByTestId('active-duration-77')).toHaveTextContent('1h04m')
  })

  it('omits the duration chip for an item with no observed activity yet', () => {
    const pipeline = pipelineWith({ triage: [buildItem(88)] })
    render(<ActiveGrid pipeline={pipeline} events={[]} now={Date.now()} />)

    expect(screen.getByTestId('active-tile-88')).toBeInTheDocument()
    expect(screen.queryByTestId('active-duration-88')).toBeNull()
  })

  // ── #17: stage-coloured dot + `stage / total` duration instead of "LIVE" ────

  // A transcript_line at a chosen ISO time carrying a `source` (the stage/role
  // proxy) so stage transitions are observable to `stageTransitionTs`.
  const eventAtSource = (id, iso, source) => ({
    type: 'transcript_line',
    timestamp: iso,
    data: { issue: id, line: `working on ${id}`, source },
  })

  it('shows `stage / total` when a stage transition is observed in the item events', () => {
    // Item first seen in triage at 10:00, transitions to reviewer at 10:10.
    const pipeline = pipelineWith({ review: [buildItem(55, 'Long one')] })
    const events = [
      eventAtSource(55, '2026-07-27T10:00:00Z', 'triage'),
      eventAtSource(55, '2026-07-27T10:10:00Z', 'reviewer'),
    ]
    const now = Date.parse('2026-07-27T10:12:00Z')
    render(<ActiveGrid pipeline={pipeline} events={events} now={now} />)
    // stage = 2m (since 10:10), total = 12m (since 10:00).
    expect(screen.getByTestId('active-duration-55')).toHaveTextContent('2m / 12m')
  })

  it('shows just the total when no stage transition is derivable', () => {
    const pipeline = pipelineWith({ implement: [buildItem(42)] })
    // Single source throughout → no transition → total only.
    const events = [
      eventAtSource(42, '2026-07-27T10:00:00Z', 'implementer'),
      eventAtSource(42, '2026-07-27T10:05:00Z', 'implementer'),
    ]
    const now = Date.parse('2026-07-27T10:12:00Z')
    render(<ActiveGrid pipeline={pipeline} events={events} now={now} />)
    const dur = screen.getByTestId('active-duration-42')
    expect(dur).toHaveTextContent('12m')
    expect(dur.textContent).not.toContain('/')
  })

  it('paints the tile live dot in the item stage colour (classic palette)', () => {
    const pipeline = pipelineWith({
      triage: [buildItem(11)],
      review: [buildItem(44)],
    })
    render(<ActiveGrid pipeline={pipeline} events={eventsFor(11, 44)} />)
    // triage → yellow, review → orange (classic PIPELINE_STAGES palette).
    expect(screen.getByTestId('active-stage-dot-11')).toHaveAttribute('data-stage-color', 'yellow')
    expect(screen.getByTestId('active-stage-dot-44')).toHaveAttribute('data-stage-color', 'orange')
  })

  it('drills into an item (focus) when its tile header is clicked', () => {
    const calls = []
    const select = (kind, value) => calls.push([kind, value])
    const pipeline = pipelineWithBuilding([buildItem(42, 'Fix login')])
    render(<ActiveGrid pipeline={pipeline} events={eventsFor(42)} select={select} />)

    fireEvent.click(screen.getByTestId('active-tile-header-42'))
    // Switches back to focus mode and selects the clicked item.
    expect(calls).toContainEqual(['mode', 'focus'])
    expect(calls).toContainEqual(['item', 42])
  })

  it('blinks the stage dot while an item is actively working, solid while queued (#18)', () => {
    const pipeline = pipelineWith({
      implement: [
        { id: 1, title: 'Working', status: 'active' },
        { id: 2, title: 'Queued', status: 'queued' },
      ],
    })
    render(<ActiveGrid pipeline={pipeline} events={eventsFor(1, 2)} now={Date.parse('2026-07-26T12:10:00Z')} />)
    // Actively-working item → the stage dot pulses; queued item → solid dot.
    expect(screen.getByTestId('active-stage-dot-1')).toHaveAttribute('data-working', 'true')
    expect(screen.getByTestId('active-stage-dot-2')).toHaveAttribute('data-working', 'false')
  })
})
