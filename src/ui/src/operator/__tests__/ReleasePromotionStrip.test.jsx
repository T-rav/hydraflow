import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ReleasePromotionStrip } from '../ReleasePromotionStrip'

// ReleasePromotionStrip (epic #10556 follow-up) consumes the
// `toReleasePromotion(...)` view model and renders the compact staging↔main
// promotion strip: a colour-coded state badge + dot, the open RC PR (linked),
// the last-RC marker, cadence, and the promotion loop's health dot. It renders
// bare (no explicit ThemeProvider) like the other operator component tests —
// the primitives resolve their colours from the dark-first default token mode.

function model(over = {}) {
  return {
    state: 'promoting',
    enabled: true,
    commitsAhead: 5,
    openPr: { number: 123, url: 'https://github.com/acme/repo/pull/123' },
    lastRc: { name: 'rc/2026-07-24-1200', ts: '2026-07-24T12:00:00Z' },
    cadenceHours: 4,
    cadenceProgressHours: 1.5,
    loop: { status: 'ok', severity: 'ok' },
    ...over,
  }
}

describe('ReleasePromotionStrip', () => {
  it('renders the strip container', () => {
    render(<ReleasePromotionStrip release={model()} />)
    expect(screen.getByTestId('release-promotion-strip')).toBeInTheDocument()
  })

  it('renders the colour-coded state label with its severity class on the dot', () => {
    render(<ReleasePromotionStrip release={model({ state: 'promoting' })} />)
    expect(screen.getByTestId('release-state')).toHaveTextContent('promoting')
    expect(screen.getByTestId('release-state-dot')).toHaveClass('promoting')
  })

  it('links the open RC promotion PR to its GitHub URL', () => {
    render(<ReleasePromotionStrip release={model()} />)
    const link = screen.getByTestId('release-open-pr')
    expect(link).toHaveTextContent('123')
    expect(link).toHaveAttribute('href', 'https://github.com/acme/repo/pull/123')
    expect(link).toHaveAttribute('target', '_blank')
  })

  it('renders the in-sync state label and shows no PR link', () => {
    render(<ReleasePromotionStrip release={model({ state: 'in_sync', openPr: null })} />)
    expect(screen.getByTestId('release-state')).toHaveTextContent('in sync')
    expect(screen.queryByTestId('release-open-pr')).toBeNull()
  })

  it('shows the staging-ahead count when behind', () => {
    render(<ReleasePromotionStrip release={model({ state: 'behind', commitsAhead: 7, openPr: null })} />)
    expect(screen.getByTestId('release-commits-ahead')).toHaveTextContent('7')
  })

  it('renders the promotion loop health dot when the loop has reported', () => {
    render(<ReleasePromotionStrip release={model({ loop: { status: 'error', severity: 'bad' } })} />)
    expect(screen.getByTestId('release-loop')).toBeInTheDocument()
  })

  it('renders gracefully with no release prop (unknown state, no PR link)', () => {
    render(<ReleasePromotionStrip />)
    expect(screen.getByTestId('release-promotion-strip')).toBeInTheDocument()
    expect(screen.getByTestId('release-state')).toHaveTextContent('unknown')
    expect(screen.queryByTestId('release-open-pr')).toBeNull()
  })
})
