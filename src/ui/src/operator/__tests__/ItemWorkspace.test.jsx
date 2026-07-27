import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'
import { ItemWorkspace } from '../ItemWorkspace'

// ItemWorkspace (epic #10556, Task 4) is the operator console's detail slot: a
// tabbed workspace (Transcript default | Diff | PR | Timeline) over the selected
// item's transcript view model from `toTranscript(...)` (Task 1). It replaces
// the last shell placeholder. Tests pass row literals shaped like
// `toTranscript(...)` output so the component is decoupled from the adapter.

const row = (over = {}) => ({
  ts: '2026-07-26T12:00:00Z',
  kind: 'agent',
  text: 'thinking',
  meta: { raw: false, issue: 42, pr: null },
  ...over,
})

function transcript() {
  return [
    row({ ts: '2026-07-26T12:00:01Z', kind: 'read', text: 'reading config.py' }),
    row({ ts: '2026-07-26T12:00:02Z', kind: 'edit', text: 'writing config.py' }),
    row({ ts: '2026-07-26T12:00:03Z', kind: 'run', text: '$ make quality' }),
    row({ ts: '2026-07-26T12:00:04Z', kind: 'pass', text: 'all tests pass' }),
  ]
}

describe('ItemWorkspace', () => {
  it('renders without crashing and defaults to the Transcript tab', () => {
    render(<ItemWorkspace item="42" transcript={transcript()} mode="focus" />)
    expect(screen.getByTestId('item-workspace')).toBeInTheDocument()
    expect(screen.getByTestId('workspace-tab-transcript')).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByTestId('transcript-stream')).toBeInTheDocument()
  })

  it('renders the four tabs', () => {
    render(<ItemWorkspace item="42" transcript={transcript()} />)
    for (const key of ['transcript', 'diff', 'pr', 'timeline']) {
      expect(screen.getByTestId(`workspace-tab-${key}`)).toBeInTheDocument()
    }
  })

  it('shows the item id in the header when an item is selected', () => {
    render(<ItemWorkspace item="42" transcript={transcript()} />)
    expect(screen.getByTestId('item-workspace-header')).toHaveTextContent('#42')
  })

  it('never renders `#undefined` as a header when no item is selected', () => {
    render(<ItemWorkspace item={null} transcript={transcript()} />)
    expect(screen.getByTestId('item-workspace')).toBeInTheDocument()
    expect(screen.queryByTestId('item-workspace-header')).toBeNull()
    expect(screen.queryByText(/#undefined/)).toBeNull()
    expect(document.body.textContent).not.toContain('#undefined')
  })

  it('shows a live indicator on the transcript when an item is selected (active)', () => {
    render(<ItemWorkspace item="42" transcript={transcript()} />)
    expect(screen.getByTestId('transcript-live')).toBeInTheDocument()
  })

  it('shows no live indicator when no item is selected', () => {
    render(<ItemWorkspace item={null} transcript={transcript()} />)
    expect(screen.queryByTestId('transcript-live')).toBeNull()
  })

  it('switches to the Diff tab and lists the edit rows', () => {
    render(<ItemWorkspace item="42" transcript={transcript()} />)
    fireEvent.click(screen.getByTestId('workspace-tab-diff'))
    expect(screen.getByTestId('workspace-tab-diff')).toHaveAttribute('aria-selected', 'true')
    const diff = screen.getByTestId('workspace-diff')
    expect(within(diff).getByText('writing config.py')).toBeInTheDocument()
    // Non-edit rows are not part of the diff view.
    expect(within(diff).queryByText('reading config.py')).toBeNull()
  })

  it('switches to the PR tab and surfaces the PR number when present', () => {
    const rows = [...transcript(), row({ kind: 'agent', text: 'review posted', meta: { pr: 528, issue: null } })]
    render(<ItemWorkspace item="528" transcript={rows} />)
    fireEvent.click(screen.getByTestId('workspace-tab-pr'))
    expect(screen.getByTestId('workspace-pr')).toHaveTextContent('PR #528')
  })

  it('shows a calm empty state on the PR tab when there is no PR', () => {
    render(<ItemWorkspace item="42" transcript={transcript()} />)
    fireEvent.click(screen.getByTestId('workspace-tab-pr'))
    expect(screen.getByTestId('workspace-pr')).toHaveTextContent(/no pr/i)
  })

  it('switches to the Timeline tab and renders grouped phase rows', () => {
    render(<ItemWorkspace item="42" transcript={transcript()} />)
    fireEvent.click(screen.getByTestId('workspace-tab-timeline'))
    expect(screen.getByTestId('workspace-timeline')).toBeInTheDocument()
    expect(screen.getAllByTestId('timeline-row').length).toBeGreaterThan(0)
  })
})
