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

const buildItem = (id, title = `Issue #${id}`) => ({ id, title, status: 'active' })

// Raw WS events shaped like the reducer stores them (as toTranscript consumes).
function eventsFor(...ids) {
  return ids.map((id, i) => ({
    type: 'transcript_line',
    timestamp: `2026-07-26T12:00:0${i}Z`,
    data: { issue: id, line: `working on ${id}` },
  }))
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
    expect(screen.getAllByTestId('transcript-live')).toHaveLength(2)
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
})
