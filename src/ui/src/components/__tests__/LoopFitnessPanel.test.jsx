import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

const mockUseHydraFlow = vi.fn()

vi.mock('../../context/HydraFlowContext', () => ({
  useHydraFlow: (...args) => mockUseHydraFlow(...args),
}))

const { LoopFitnessPanel } = await import('../LoopFitnessPanel')

function defaultContext(overrides = {}) {
  return {
    loopFitness: {},
    ...overrides,
  }
}

beforeEach(() => {
  mockUseHydraFlow.mockReturnValue(defaultContext())
})

describe('LoopFitnessPanel', () => {
  it('shows empty state when loopFitness is empty', () => {
    render(<LoopFitnessPanel />)
    expect(screen.getByTestId('loop-fitness-panel-root')).toBeInTheDocument()
    expect(screen.getByText('No loop fitness data available yet.')).toBeInTheDocument()
  })

  it('shows empty state when loopFitness is null', () => {
    mockUseHydraFlow.mockReturnValue(defaultContext({ loopFitness: null }))
    render(<LoopFitnessPanel />)
    expect(screen.getByText('No loop fitness data available yet.')).toBeInTheDocument()
  })

  it('renders scored loop rows with score, kind, confidence, and sample_count', () => {
    mockUseHydraFlow.mockReturnValue(defaultContext({
      loopFitness: {
        ImplementerLoop: {
          worker_name: 'ImplementerLoop',
          kind: 'scored',
          score: 0.82,
          components: { test_coverage: 0.9, quality_pass_rate: 0.74 },
          sample_count: 12,
          confidence: 'ok',
          notes: null,
          timestamp: '2026-06-30T00:00:00Z',
        },
      },
    }))
    render(<LoopFitnessPanel />)
    expect(screen.getByTestId('loop-fitness-row-ImplementerLoop')).toBeInTheDocument()
    expect(screen.getByTestId('loop-fitness-name-ImplementerLoop')).toBeInTheDocument()
    expect(screen.getByTestId('loop-fitness-score-ImplementerLoop').textContent).toBe('0.820')
    expect(screen.getByText('scored')).toBeInTheDocument()
    expect(screen.getByTestId('confidence-ok')).toBeInTheDocument()
    expect(screen.getByText('12')).toBeInTheDocument()
  })

  it('renders housekeeping loop rows', () => {
    mockUseHydraFlow.mockReturnValue(defaultContext({
      loopFitness: {
        WikiLoop: {
          worker_name: 'WikiLoop',
          kind: 'housekeeping',
          score: 0.65,
          components: { freshness: 0.65 },
          sample_count: 5,
          confidence: 'ok',
          notes: null,
          timestamp: '2026-06-30T00:00:00Z',
        },
      },
    }))
    render(<LoopFitnessPanel />)
    expect(screen.getByText('housekeeping')).toBeInTheDocument()
    expect(screen.getByTestId('loop-fitness-row-WikiLoop')).toBeInTheDocument()
  })

  it('renders null score as "n/a", not 0', () => {
    mockUseHydraFlow.mockReturnValue(defaultContext({
      loopFitness: {
        TriageLoop: {
          worker_name: 'TriageLoop',
          kind: 'scored',
          score: null,
          components: {},
          sample_count: 2,
          confidence: 'insufficient_data',
          notes: null,
          timestamp: '2026-06-30T00:00:00Z',
        },
      },
    }))
    render(<LoopFitnessPanel />)
    const scoreEl = screen.getByTestId('loop-fitness-score-TriageLoop')
    expect(scoreEl.textContent).toBe('n/a')
    // Must not render '0' as a score
    expect(scoreEl.textContent).not.toBe('0')
    expect(scoreEl.textContent).not.toBe('0.000')
  })

  it('renders score of 0 as "0.000", not "n/a"', () => {
    mockUseHydraFlow.mockReturnValue(defaultContext({
      loopFitness: {
        ZeroScoredLoop: {
          worker_name: 'ZeroScoredLoop',
          kind: 'scored',
          score: 0,
          components: {},
          sample_count: 8,
          confidence: 'ok',
          notes: null,
          timestamp: '2026-06-30T00:00:00Z',
        },
      },
    }))
    render(<LoopFitnessPanel />)
    const scoreEl = screen.getByTestId('loop-fitness-score-ZeroScoredLoop')
    expect(scoreEl.textContent).toBe('0.000')
    // Must not render as "n/a"
    expect(scoreEl.textContent).not.toBe('n/a')
  })

  it('renders insufficient_data confidence visually distinct from ok', () => {
    mockUseHydraFlow.mockReturnValue(defaultContext({
      loopFitness: {
        AlphaLoop: {
          worker_name: 'AlphaLoop',
          kind: 'scored',
          score: null,
          components: {},
          sample_count: 1,
          confidence: 'insufficient_data',
          notes: null,
          timestamp: '2026-06-30T00:00:00Z',
        },
        BetaLoop: {
          worker_name: 'BetaLoop',
          kind: 'scored',
          score: 0.9,
          components: {},
          sample_count: 20,
          confidence: 'ok',
          notes: null,
          timestamp: '2026-06-30T00:00:00Z',
        },
      },
    }))
    render(<LoopFitnessPanel />)
    const insufficientBadge = screen.getByTestId('confidence-insufficient')
    const okBadge = screen.getByTestId('confidence-ok')
    // They must both exist and be distinct elements
    expect(insufficientBadge).toBeInTheDocument()
    expect(okBadge).toBeInTheDocument()
    // Visually distinct: the insufficient badge shows 'insufficient data' label
    expect(insufficientBadge.textContent).toBe('insufficient data')
    expect(okBadge.textContent).toBe('ok')
  })

  it('sorts rows by worker_name alphabetically, not by score', () => {
    // ZebraLoop has a higher score than AlphaLoop — it must NOT jump above it
    mockUseHydraFlow.mockReturnValue(defaultContext({
      loopFitness: {
        ZebraLoop: {
          worker_name: 'ZebraLoop',
          kind: 'scored',
          score: 0.99,
          components: {},
          sample_count: 30,
          confidence: 'ok',
          notes: null,
          timestamp: '2026-06-30T00:00:00Z',
        },
        AlphaLoop: {
          worker_name: 'AlphaLoop',
          kind: 'scored',
          score: 0.10,
          components: {},
          sample_count: 15,
          confidence: 'ok',
          notes: null,
          timestamp: '2026-06-30T00:00:00Z',
        },
        MidLoop: {
          worker_name: 'MidLoop',
          kind: 'housekeeping',
          score: 0.55,
          components: {},
          sample_count: 8,
          confidence: 'ok',
          notes: null,
          timestamp: '2026-06-30T00:00:00Z',
        },
      },
    }))
    render(<LoopFitnessPanel />)
    const rows = screen.getByTestId('loop-fitness-rows')
    const rowElements = rows.querySelectorAll('[data-testid^="loop-fitness-row-"]')
    const names = Array.from(rowElements).map(el => el.getAttribute('data-testid').replace('loop-fitness-row-', ''))
    // Alphabetical order: AlphaLoop < MidLoop < ZebraLoop
    expect(names).toEqual(['AlphaLoop', 'MidLoop', 'ZebraLoop'])
    // The highest-scoring ZebraLoop is last, not first
    expect(names[0]).toBe('AlphaLoop')
    expect(names[names.length - 1]).toBe('ZebraLoop')
  })

  it('renders raw components when present', () => {
    mockUseHydraFlow.mockReturnValue(defaultContext({
      loopFitness: {
        ImplementerLoop: {
          worker_name: 'ImplementerLoop',
          kind: 'scored',
          score: 0.75,
          components: { test_coverage: 0.8, pr_merge_rate: 0.7 },
          sample_count: 10,
          confidence: 'ok',
          notes: null,
          timestamp: '2026-06-30T00:00:00Z',
        },
      },
    }))
    render(<LoopFitnessPanel />)
    const componentsEl = screen.getByTestId('loop-fitness-components')
    expect(componentsEl).toBeInTheDocument()
    expect(componentsEl.textContent).toContain('test_coverage')
    expect(componentsEl.textContent).toContain('pr_merge_rate')
  })

  it('renders notes when present', () => {
    mockUseHydraFlow.mockReturnValue(defaultContext({
      loopFitness: {
        ReviewLoop: {
          worker_name: 'ReviewLoop',
          kind: 'scored',
          score: 0.6,
          components: {},
          sample_count: 4,
          confidence: 'ok',
          notes: 'Score suppressed: low sample window.',
          timestamp: '2026-06-30T00:00:00Z',
        },
      },
    }))
    render(<LoopFitnessPanel />)
    expect(screen.getByTestId('loop-fitness-notes-ReviewLoop')).toBeInTheDocument()
    expect(screen.getByText('Score suppressed: low sample window.')).toBeInTheDocument()
  })
})
