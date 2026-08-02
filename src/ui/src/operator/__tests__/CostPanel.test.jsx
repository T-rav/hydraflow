import { describe, it, expect } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { CostPanel } from '../CostPanel'

// CostPanel (#10785) consumes the `toCostByRepo(...)` view model and renders the
// repo + per-repo cost-per-model readout over a rolling 24h window. Tests pass
// VM literals (not raw payloads) to stay decoupled from the adapter internals,
// mirroring the VitalsCard / PipelineRail component-test pattern.

const modelRow = (over = {}) => ({
  model: 'sonnet',
  costUsd: 3.0,
  costUnknown: false,
  calls: 2,
  tokensIn: 300,
  tokensOut: 150,
  ...over,
})

const vm = (over = {}) => ({
  windowLabel: 'last 24h',
  totalCostUsd: 3.5,
  totalCostUnknown: false,
  all: [modelRow(), modelRow({ model: 'haiku', costUsd: 0.5, tokensIn: 40, tokensOut: 20 })],
  repos: [],
  ...over,
})

describe('CostPanel', () => {
  it('renders the header, window label and total spend', () => {
    render(<CostPanel cost={vm()} />)
    const panel = screen.getByTestId('cost-panel')
    expect(panel).toHaveTextContent('Cost / model')
    expect(panel).toHaveTextContent('last 24h')
    expect(screen.getByTestId('cost-total')).toHaveTextContent('$3.50')
  })

  it('renders one row per aggregate model with its cost', () => {
    render(<CostPanel cost={vm()} />)
    expect(screen.getByTestId('cost-model-sonnet')).toHaveTextContent('$3.00')
    expect(screen.getByTestId('cost-model-haiku')).toHaveTextContent('$0.50')
  })

  it('renders an unpriced model as "unknown", never $0.00 (#9821)', () => {
    render(<CostPanel cost={vm({
      all: [modelRow({ model: 'glm', costUsd: 0, costUnknown: true })],
      totalCostUnknown: true,
    })} />)
    const row = screen.getByTestId('cost-model-glm')
    expect(row).toHaveTextContent('unknown')
    expect(row).not.toHaveTextContent('$0.00')
  })

  it('shows a calm empty state when there is no spend', () => {
    render(<CostPanel cost={vm({ all: [], totalCostUsd: 0 })} />)
    expect(screen.getByTestId('cost-empty')).toHaveTextContent('no spend recorded')
    expect(screen.queryByTestId('cost-model-sonnet')).toBeNull()
  })

  it('omits the per-repo breakdown for a single-repo install', () => {
    render(<CostPanel cost={vm({
      repos: [{ repo: 'org-a', totalCostUsd: 3.5, byModel: [modelRow()] }],
    })} />)
    // One repo → the aggregate list already IS that repo; no breakdown section.
    expect(screen.queryByTestId('cost-repos')).toBeNull()
  })

  it('renders a per-repo breakdown for a multi-repo install', () => {
    render(<CostPanel cost={vm({
      repos: [
        { repo: 'org-b', totalCostUsd: 2.5, byModel: [modelRow({ model: 'sonnet', costUsd: 2.0 })] },
        { repo: 'org-a', totalCostUsd: 1.0, byModel: [modelRow({ model: 'sonnet', costUsd: 1.0 })] },
      ],
    })} />)
    expect(screen.getByTestId('cost-repos')).toBeInTheDocument()
    const orgB = screen.getByTestId('cost-repo-org-b')
    expect(orgB).toHaveTextContent('org-b')
    expect(orgB).toHaveTextContent('$2.50')
    expect(within(orgB).getByTestId('cost-repo-org-b-model-sonnet')).toHaveTextContent('$2.00')
    expect(screen.getByTestId('cost-repo-org-a')).toHaveTextContent('$1.00')
  })

  it('renders the empty state without a cost prop (backward-compatible default)', () => {
    render(<CostPanel />)
    expect(screen.getByTestId('cost-panel')).toBeInTheDocument()
    expect(screen.getByTestId('cost-empty')).toBeInTheDocument()
  })
})
