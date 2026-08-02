/**
 * SettingsDrawer — the operator console's full-configuration drawer
 * (epic #10556 follow-up).
 *
 * Opened from the SettingsSummary gear, this slides the full configuration into
 * a modal over the operator console. Its body is TABBED (#10786): the default
 * Workflow tab renders the operator-first `WorkflowConfigPanel` (pipeline knobs
 * grouped by stage/concern), and the System tab REUSES the existing
 * `SystemPanel` component (loops, intervals, watchdog) — it does NOT reimplement
 * or fork any of that UI or state.
 *
 * Reuse / provider scope: `App.jsx` wraps both the classic dashboard AND the
 * operator console in a single `<HydraFlowProvider>`, so everything the
 * operator console renders — including this drawer — is already inside that
 * provider. `SystemPanel` reads the rest of its state from `useHydraFlow()`
 * directly (config, events, pipeline, selectedRepoSlug, …); its background-
 * worker data + mutation handlers arrive as props, exactly as `AppContent`
 * passes them. This drawer pulls those SAME handlers from the SAME context and
 * threads them through — reuse, not a second copy of the state.
 *
 * Contract the tests pin: renders nothing while `open` is false; when `open`
 * it renders `data-testid="settings-drawer"` plus a close affordance
 * (`settings-drawer-close`) and a backdrop (`settings-drawer-backdrop`), both
 * firing `onClose`; the Workflow tab is active by default, and the
 * `settings-tab-system` tab switches the body to the reused `SystemPanel`.
 * Presentation only beyond that context read; every colour / space value
 * resolves from `useTokens()` so light + dark fall out of the console's
 * ThemeProvider mode.
 */

import React from 'react'
import { useTokens, Text } from '../styles/primitives'
import { useHydraFlow } from '../context/HydraFlowContext'
import { SystemPanel } from '../components/SystemPanel'
import { WorkflowConfigPanel } from './WorkflowConfigPanel'

function makeStyles(t) {
  return {
    overlay: {
      position: 'fixed',
      inset: 0,
      zIndex: 1000,
      display: 'flex',
      alignItems: 'stretch',
      justifyContent: 'flex-end',
    },
    backdrop: {
      position: 'absolute',
      inset: 0,
      border: 'none',
      padding: 0,
      margin: 0,
      cursor: 'pointer',
      // Token-derived scrim (no colour literal): a translucent wash of the base
      // background, so it dims consistently in both light and dark modes.
      background: `color-mix(in srgb, ${t.color.bg} 68%, transparent)`,
    },
    panel: {
      position: 'relative',
      zIndex: 1,
      display: 'flex',
      flexDirection: 'column',
      width: 'min(920px, 100%)',
      maxWidth: '100%',
      height: '100%',
      background: t.color.surface,
      borderLeft: `1px solid ${t.color.border}`,
      boxShadow: t.shadow.lg,
    },
    panelHeader: {
      display: 'flex',
      alignItems: 'center',
      gap: t.space.sm,
      flexShrink: 0,
      padding: `${t.space.sm}px ${t.space.md}px`,
      borderBottom: `1px solid ${t.color.border}`,
      background: t.color.surfaceInset,
    },
    spacer: { flex: '1 1 auto' },
    tabs: {
      display: 'flex',
      gap: t.space.xs,
      flexShrink: 0,
      padding: `0 ${t.space.md}px`,
      borderBottom: `1px solid ${t.color.border}`,
      background: t.color.surfaceInset,
    },
    tab: {
      appearance: 'none',
      background: 'transparent',
      // Per-side longhands only (no `border` shorthand) so the border
      // shorthand/longhand guard (#10583) stays green.
      borderTop: 'none',
      borderRight: 'none',
      borderLeft: 'none',
      borderBottom: '2px solid transparent',
      color: t.color.textMuted,
      cursor: 'pointer',
      font: 'inherit',
      fontSize: t.type.size.sm,
      fontWeight: t.type.weight.semibold,
      padding: `${t.space.sm}px ${t.space.sm}px`,
    },
    tabActive: {
      appearance: 'none',
      background: 'transparent',
      borderTop: 'none',
      borderRight: 'none',
      borderLeft: 'none',
      borderBottom: `2px solid ${t.color.accent}`,
      color: t.color.text,
      cursor: 'pointer',
      font: 'inherit',
      fontSize: t.type.size.sm,
      fontWeight: t.type.weight.semibold,
      padding: `${t.space.sm}px ${t.space.sm}px`,
    },
    closeBtn: {
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      flexShrink: 0,
      width: 24,
      height: 24,
      border: `1px solid ${t.color.border}`,
      borderRadius: t.radius.md,
      background: t.color.surface,
      color: t.color.text,
      cursor: 'pointer',
      font: 'inherit',
      fontSize: t.type.size.sm,
      lineHeight: 1,
    },
    body: {
      flex: '1 1 auto',
      minHeight: 0,
      overflowY: 'auto',
      overflowX: 'hidden',
    },
  }
}

/**
 * The mounted drawer body. Rendered only while open, so the context
 * subscription + SystemPanel mount cost is paid only when the drawer is shown.
 * @param {{ onClose?: () => void }} props
 */
function SettingsDrawerContent({ onClose }) {
  const t = useTokens()
  const styles = makeStyles(t)
  // The drawer body is tabbed: the new operator-first WorkflowConfigPanel is the
  // default tab; the classic SystemPanel (loops, intervals, watchdog) is the
  // second, reached via the System tab — reused, not forked.
  const [tab, setTab] = React.useState('workflow')
  // Same context handlers AppContent threads into SystemPanel — reused here so
  // the drawer shares the live state instead of forking it.
  const {
    backgroundWorkers = [],
    toggleBgWorker,
    triggerBgWorker,
    updateBgWorkerInterval,
    updateBgWorkerWatchdogTimeout,
  } = useHydraFlow()

  return (
    <div
      data-testid="settings-drawer"
      style={styles.overlay}
      role="dialog"
      aria-modal="true"
      aria-label="Configuration"
    >
      <button
        type="button"
        data-testid="settings-drawer-backdrop"
        aria-label="Close settings"
        onClick={() => onClose?.()}
        style={styles.backdrop}
      />
      <div style={styles.panel}>
        <div style={styles.panelHeader}>
          <Text size="sm" weight="bold" uppercase>Configuration</Text>
          <span style={styles.spacer} />
          <button
            type="button"
            data-testid="settings-drawer-close"
            onClick={() => onClose?.()}
            style={styles.closeBtn}
            aria-label="Close settings"
            title="Close"
          >
            ✕
          </button>
        </div>
        <div style={styles.tabs} role="tablist" aria-label="Configuration sections">
          <button
            type="button"
            role="tab"
            data-testid="settings-tab-workflow"
            aria-selected={tab === 'workflow'}
            onClick={() => setTab('workflow')}
            style={tab === 'workflow' ? styles.tabActive : styles.tab}
          >
            Workflow
          </button>
          <button
            type="button"
            role="tab"
            data-testid="settings-tab-system"
            aria-selected={tab === 'system'}
            onClick={() => setTab('system')}
            style={tab === 'system' ? styles.tabActive : styles.tab}
          >
            System
          </button>
        </div>
        <div style={styles.body}>
          {tab === 'workflow' ? (
            <WorkflowConfigPanel />
          ) : (
            <SystemPanel
              backgroundWorkers={backgroundWorkers}
              onToggleBgWorker={toggleBgWorker}
              onTriggerBgWorker={triggerBgWorker}
              onUpdateInterval={updateBgWorkerInterval}
              onUpdateWatchdogTimeout={updateBgWorkerWatchdogTimeout}
            />
          )}
        </div>
      </div>
    </div>
  )
}

/**
 * @param {{ open?: boolean, onClose?: () => void }} props
 */
export function SettingsDrawer({ open, onClose }) {
  if (!open) return null
  return <SettingsDrawerContent onClose={onClose} />
}

export default SettingsDrawer
