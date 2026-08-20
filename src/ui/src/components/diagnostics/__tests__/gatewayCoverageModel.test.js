import { describe, expect, it } from 'vitest'
import {
  EMPTY_GATEWAY_COVERAGE,
  toGatewayCoverage,
} from '../gatewayCoverageModel'

describe('gatewayCoverageModel', () => {
  it('normalizes a complete coverage claim', () => {
    const vm = toGatewayCoverage({
      status: 'complete',
      scope: 'global',
      window_label: '24h',
      coverage_percent: 80,
      known_spend_coverage_percent: 80,
      gateway_spend_usd: 8,
      bypass_spend_usd: 2,
      known_total_spend_usd: 10,
      gateway_requests: 4,
      bypass_requests: 1,
      bypassing_families: [
        { family: 'wiki_compilation', calls: 1, spend_usd: 2, providers: ['openrouter'] },
      ],
    })

    expect(vm.statusLabel).toBe('Complete')
    expect(vm.valueLabel).toBe('80.0%')
    expect(vm.scopeLabel).toBe('All repos')
    expect(vm.bypassingFamilies[0].family).toBe('wiki_compilation')
  })

  it('labels known spend as partial instead of claiming total coverage', () => {
    const vm = toGatewayCoverage({
      status: 'partial',
      coverage_percent: null,
      known_spend_coverage_percent: 100,
      unpriced_bypass_requests: 2,
    })

    expect(vm.statusLabel).toBe('Partial pricing')
    expect(vm.valueLabel).toBe('100.0% known spend')
    expect(vm.unknownRequests).toBe(2)
    expect(vm.meterLabel).toMatch(/Partial pricing/)
  })

  it('does not describe entirely unpriced observations as no spend', () => {
    const vm = toGatewayCoverage({
      status: 'partial',
      known_spend_coverage_percent: null,
      unpriced_gateway_requests: 1,
    })

    expect(vm.valueLabel).toBe('Coverage unknown')
    expect(vm.meterLabel).toMatch(/cannot be calculated/)
  })

  it('labels missing source evidence without implying a pricing-only gap', () => {
    const vm = toGatewayCoverage({
      status: 'partial',
      known_spend_coverage_percent: 100,
      unpriced_gateway_requests: 0,
      unpriced_bypass_requests: 0,
      source_data_complete: false,
    })

    expect(vm.statusLabel).toBe('Incomplete evidence')
    expect(vm.valueLabel).toBe('Coverage unknown')
    expect(vm.meterLabel).toMatch(/evidence is incomplete/i)
  })

  it('does not hide missing evidence when surviving requests are also unpriced', () => {
    const vm = toGatewayCoverage({
      status: 'partial',
      known_spend_coverage_percent: 100,
      unpriced_gateway_requests: 1,
      source_data_complete: false,
    })

    expect(vm.statusLabel).toBe('Incomplete evidence')
    expect(vm.valueLabel).toBe('Coverage unknown')
    expect(vm.sourceDataComplete).toBe(false)
    expect(vm.meterLabel).toMatch(/evidence is incomplete/i)
  })

  it('returns the frozen calm state for malformed input', () => {
    expect(toGatewayCoverage(null)).toBe(EMPTY_GATEWAY_COVERAGE)
  })
})
