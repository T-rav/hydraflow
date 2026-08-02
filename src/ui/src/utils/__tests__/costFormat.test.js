import { describe, it, expect } from 'vitest'
import { formatUsd, formatTokens } from '../costFormat'

// Shared cost/token formatters for the operator cost panel (#10785). The
// load-bearing rule: an unpriced model renders "unknown", never "$0.00" (#9821).

describe('formatUsd', () => {
  it('formats a normal cost to two decimals', () => {
    expect(formatUsd(12.3)).toBe('$12.30')
    expect(formatUsd(0.5)).toBe('$0.50')
  })

  it('renders a genuinely-zero PRICED cost as $0.00', () => {
    expect(formatUsd(0)).toBe('$0.00')
    expect(formatUsd(0, { unknown: false })).toBe('$0.00')
  })

  it('renders an UNPRICED cost as "unknown", never $0.00 (#9821)', () => {
    expect(formatUsd(0, { unknown: true })).toBe('unknown')
    expect(formatUsd(5, { unknown: true })).toBe('unknown')
  })

  it('treats a non-finite cost as unknown', () => {
    expect(formatUsd(undefined)).toBe('unknown')
    expect(formatUsd(NaN)).toBe('unknown')
    expect(formatUsd(null)).toBe('unknown')
  })

  it('never rounds a tiny non-zero cost away to $0.00', () => {
    expect(formatUsd(0.004)).toBe('<$0.01')
    expect(formatUsd(0.009)).toBe('<$0.01')
  })
})

describe('formatTokens', () => {
  it('compacts thousands and millions', () => {
    expect(formatTokens(1234)).toBe('1.2k')
    expect(formatTokens(2_500_000)).toBe('2.5M')
  })

  it('renders small counts verbatim', () => {
    expect(formatTokens(0)).toBe('0')
    expect(formatTokens(42)).toBe('42')
  })

  it('coerces non-finite / negative to 0', () => {
    expect(formatTokens(undefined)).toBe('0')
    expect(formatTokens(-5)).toBe('0')
  })
})
