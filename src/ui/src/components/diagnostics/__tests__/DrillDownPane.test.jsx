import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'

vi.mock('echarts-for-react', () => ({
  default: () => <div data-testid="echarts" />,
}))

import { DrillDownPane } from '../DrillDownPane'

describe('DrillDownPane', () => {
  it('renders subprocess hierarchy', () => {
    render(<DrillDownPane runData={{
      summary: { issue_number: 42, phase: 'implement', run_id: 1, tokens: { prompt_tokens: 1000 } },
      subprocesses: [
        { subprocess_idx: 0, backend: 'claude', tokens: { prompt_tokens: 500, completion_tokens: 200 }, tool_calls: [], skill_results: [] },
        { subprocess_idx: 1, backend: 'claude', tokens: { prompt_tokens: 500, completion_tokens: 100 }, tool_calls: [], skill_results: [] },
      ],
    }} onClose={() => {}} />)
    expect(screen.getByText(/subprocess-0/)).toBeInTheDocument()
    expect(screen.getByText(/subprocess-1/)).toBeInTheDocument()
  })

  it('renders empty when no run', () => {
    render(<DrillDownPane runData={null} onClose={() => {}} />)
    expect(screen.getByText(/Select a row/i)).toBeInTheDocument()
  })
})
