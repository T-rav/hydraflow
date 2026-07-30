import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'
import { SettingsSummary } from '../SettingsSummary'
import { toSettingsSummary } from '../model/settingsSummary'

// SettingsSummary (epic #10556 follow-up) renders the at-a-glance KEY settings
// as compact labelled chips plus a gear/"Settings" affordance that opens the
// full System configuration drawer via `onOpenSettings`. It consumes the
// `toSettingsSummary(...)` view model, so tests feed it that adapter's output.

const summary = () => toSettingsSummary({
  model: 'claude-opus-4-8',
  max_workers: 5,
  max_planners: 2,
  max_reviewers: 3,
  batch_size: 5,
  queue_strategy: 'weighted_mix',
  merge_policy_enabled: true,
})

describe('SettingsSummary', () => {
  it('renders the panel container', () => {
    render(<SettingsSummary summary={summary()} />)
    expect(screen.getByTestId('settings-summary')).toBeInTheDocument()
  })

  it('renders a labelled chip per key setting', () => {
    render(<SettingsSummary summary={summary()} />)
    const model = screen.getByTestId('settings-item-model')
    expect(model).toHaveTextContent('Model')
    expect(model).toHaveTextContent('claude-opus-4-8')

    expect(within(screen.getByTestId('settings-item-workers')).getByText('5')).toBeInTheDocument()
    expect(screen.getByTestId('settings-item-queue')).toHaveTextContent('weighted_mix')
    expect(screen.getByTestId('settings-item-merge')).toHaveTextContent('on')
  })

  it('fires onOpenSettings when the gear button is clicked', () => {
    const onOpenSettings = vi.fn()
    render(<SettingsSummary summary={summary()} onOpenSettings={onOpenSettings} />)
    fireEvent.click(screen.getByTestId('settings-open'))
    expect(onOpenSettings).toHaveBeenCalledTimes(1)
  })

  it('does not crash when the gear is clicked without a handler', () => {
    render(<SettingsSummary summary={summary()} />)
    expect(() => fireEvent.click(screen.getByTestId('settings-open'))).not.toThrow()
  })

  it('renders gracefully with no summary prop', () => {
    render(<SettingsSummary />)
    expect(screen.getByTestId('settings-summary')).toBeInTheDocument()
    expect(screen.getByTestId('settings-open')).toBeInTheDocument()
    expect(screen.queryByTestId('settings-item-model')).toBeNull()
  })
})
