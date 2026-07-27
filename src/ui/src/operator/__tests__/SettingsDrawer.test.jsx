import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { SettingsDrawer } from '../SettingsDrawer'

// SettingsDrawer (epic #10556 follow-up) slides the full classic System-tab
// configuration into a modal by REUSING SystemPanel. These tests assert the
// drawer WIRING (open/closed, close + backdrop affordances, that it mounts
// SystemPanel and threads the context handlers through) — NOT SystemPanel's
// internals, so SystemPanel is stubbed and useHydraFlow is mocked to keep the
// mount lightweight.

const systemPanelProps = vi.fn()

vi.mock('../../components/SystemPanel', () => ({
  SystemPanel: (props) => {
    systemPanelProps(props)
    return <div data-testid="system-panel-stub" />
  },
}))

const toggleBgWorker = vi.fn()
const triggerBgWorker = vi.fn()
const updateBgWorkerInterval = vi.fn()
const updateBgWorkerWatchdogTimeout = vi.fn()
const backgroundWorkers = [{ name: 'ci_monitor', status: 'ok', enabled: true }]

vi.mock('../../context/HydraFlowContext', () => ({
  useHydraFlow: () => ({
    backgroundWorkers,
    toggleBgWorker,
    triggerBgWorker,
    updateBgWorkerInterval,
    updateBgWorkerWatchdogTimeout,
  }),
}))

describe('SettingsDrawer', () => {
  it('renders nothing when closed', () => {
    const { container } = render(<SettingsDrawer open={false} onClose={vi.fn()} />)
    expect(screen.queryByTestId('settings-drawer')).toBeNull()
    expect(screen.queryByTestId('system-panel-stub')).toBeNull()
    expect(container).toBeEmptyDOMElement()
  })

  it('renders the drawer and reuses SystemPanel when open', () => {
    render(<SettingsDrawer open onClose={vi.fn()} />)
    expect(screen.getByTestId('settings-drawer')).toBeInTheDocument()
    expect(screen.getByTestId('system-panel-stub')).toBeInTheDocument()
  })

  it('threads the context worker data + handlers into SystemPanel (reuse, not fork)', () => {
    systemPanelProps.mockClear()
    render(<SettingsDrawer open onClose={vi.fn()} />)
    expect(systemPanelProps).toHaveBeenCalled()
    const props = systemPanelProps.mock.calls.at(-1)[0]
    expect(props.backgroundWorkers).toBe(backgroundWorkers)
    expect(props.onToggleBgWorker).toBe(toggleBgWorker)
    expect(props.onTriggerBgWorker).toBe(triggerBgWorker)
    expect(props.onUpdateInterval).toBe(updateBgWorkerInterval)
    expect(props.onUpdateWatchdogTimeout).toBe(updateBgWorkerWatchdogTimeout)
  })

  it('fires onClose from the close button', () => {
    const onClose = vi.fn()
    render(<SettingsDrawer open onClose={onClose} />)
    fireEvent.click(screen.getByTestId('settings-drawer-close'))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('fires onClose when the backdrop is clicked', () => {
    const onClose = vi.fn()
    render(<SettingsDrawer open onClose={onClose} />)
    fireEvent.click(screen.getByTestId('settings-drawer-backdrop'))
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
