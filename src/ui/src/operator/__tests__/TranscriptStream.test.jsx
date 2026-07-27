import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { TranscriptStream } from '../TranscriptStream'

// TranscriptStream (epic #10556, Task 4) renders the per-item formatted live
// transcript that replaces today's raw `transcript line#…` wall. It consumes
// the already-formatted rows produced by `toTranscript(...)` (Task 1) — each
// row is `{ ts, kind, text, meta }`, kind ∈ read|edit|run|pass|fail|agent — and
// renders one formatted row per entry, a live indicator when the focused item
// is active, and a "raw" escape-hatch toggle that shows the unparsed lines.
//
// Tests pass row literals shaped exactly like `toTranscript(...)` output so the
// component is decoupled from the adapter (mirrors the PipelineRail / Activity
// Drawer tests).

const row = (over = {}) => ({
  ts: '2026-07-26T12:00:00Z',
  kind: 'agent',
  text: 'thinking',
  meta: { raw: false },
  ...over,
})

function allKinds() {
  return [
    row({ ts: '2026-07-26T12:00:01Z', kind: 'read', text: 'reading config.py' }),
    row({ ts: '2026-07-26T12:00:02Z', kind: 'edit', text: 'writing config.py' }),
    row({ ts: '2026-07-26T12:00:03Z', kind: 'run', text: '$ make quality' }),
    row({ ts: '2026-07-26T12:00:04Z', kind: 'pass', text: 'all tests pass' }),
    row({ ts: '2026-07-26T12:00:05Z', kind: 'fail', text: 'boom: failed' }),
    row({ ts: '2026-07-26T12:00:06Z', kind: 'agent', text: 'deciding next step' }),
  ]
}

describe('TranscriptStream', () => {
  it('renders without crashing on empty rows and shows an empty state', () => {
    render(<TranscriptStream rows={[]} />)
    expect(screen.getByTestId('transcript-stream')).toBeInTheDocument()
    expect(screen.getByTestId('transcript-empty')).toBeInTheDocument()
    expect(screen.queryByTestId('transcript-row')).toBeNull()
  })

  it('renders one formatted row per entry, tagged with its kind', () => {
    render(<TranscriptStream rows={allKinds()} />)
    const rows = screen.getAllByTestId('transcript-row')
    expect(rows).toHaveLength(6)
    const kinds = rows.map(r => r.getAttribute('data-kind'))
    expect(kinds).toEqual(['read', 'edit', 'run', 'pass', 'fail', 'agent'])
    expect(screen.getByText('reading config.py')).toBeInTheDocument()
    expect(screen.getByText('all tests pass')).toBeInTheDocument()
  })

  it('renders a timestamp on each formatted row', () => {
    render(<TranscriptStream rows={[row({ ts: '2026-07-26T12:00:02Z', text: 'x' })]} />)
    expect(screen.getByTestId('transcript-ts')).toHaveTextContent('12:00:02')
  })

  it('shows a live indicator when the item is active', () => {
    render(<TranscriptStream rows={allKinds()} active />)
    expect(screen.getByTestId('transcript-live')).toBeInTheDocument()
  })

  it('hides the live indicator when the item is not active', () => {
    render(<TranscriptStream rows={allKinds()} active={false} />)
    expect(screen.queryByTestId('transcript-live')).toBeNull()
  })

  it('appends new rows when the parent feeds more events', () => {
    const { rerender } = render(<TranscriptStream rows={allKinds()} />)
    expect(screen.getAllByTestId('transcript-row')).toHaveLength(6)
    rerender(
      <TranscriptStream
        rows={[...allKinds(), row({ ts: '2026-07-26T12:00:07Z', kind: 'edit', text: 'wrote NEW_FILE.py' })]}
      />,
    )
    expect(screen.getAllByTestId('transcript-row')).toHaveLength(7)
    expect(screen.getByText('wrote NEW_FILE.py')).toBeInTheDocument()
  })

  it('raw toggle shows unparsed lines instead of formatted rows', () => {
    render(<TranscriptStream rows={allKinds()} />)
    // Default: formatted rows, no raw lines.
    expect(screen.getAllByTestId('transcript-row').length).toBeGreaterThan(0)
    expect(screen.queryByTestId('transcript-raw-line')).toBeNull()

    fireEvent.click(screen.getByTestId('transcript-raw-toggle'))

    // Raw mode: unparsed lines, no formatted rows.
    expect(screen.getAllByTestId('transcript-raw-line')).toHaveLength(6)
    expect(screen.queryByTestId('transcript-row')).toBeNull()
    expect(screen.getByText('$ make quality')).toBeInTheDocument()

    // Toggling back restores the formatted stream.
    fireEvent.click(screen.getByTestId('transcript-raw-toggle'))
    expect(screen.getAllByTestId('transcript-row')).toHaveLength(6)
  })
})
