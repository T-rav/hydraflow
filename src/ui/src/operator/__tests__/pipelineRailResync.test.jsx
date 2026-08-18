import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { PipelineRail } from '../PipelineRail'

const pipeline = { stages: [{ key: 'plan', label: 'PLAN', count: 2, items: [] }] }

describe('PipelineRail resyncing chip (#11350)', () => {
  it('hides the chip when the snapshot is fresh', () => {
    render(<PipelineRail pipeline={pipeline} resyncing={false} />)
    expect(screen.queryByTestId('pipeline-resync-chip')).not.toBeInTheDocument()
  })

  it('shows the chip when the rail is resyncing', () => {
    render(<PipelineRail pipeline={pipeline} resyncing />)
    expect(screen.getByTestId('pipeline-resync-chip')).toBeInTheDocument()
  })

  it('still renders the rail itself while resyncing', () => {
    render(<PipelineRail pipeline={pipeline} resyncing />)
    expect(screen.getByTestId('pipeline-rail')).toBeInTheDocument()
  })

  it('defaults to not resyncing when the prop is omitted', () => {
    render(<PipelineRail pipeline={pipeline} />)
    expect(screen.queryByTestId('pipeline-resync-chip')).not.toBeInTheDocument()
  })
})
