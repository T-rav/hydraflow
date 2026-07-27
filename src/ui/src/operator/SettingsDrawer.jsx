/**
 * SettingsDrawer — the operator console's full-configuration drawer
 * (epic #10556 follow-up).
 *
 * Opened from the SettingsSummary gear, this slides the ENTIRE classic
 * System-tab configuration into a modal over the operator console by REUSING
 * the existing `SystemPanel` component — it does NOT reimplement or fork any of
 * that UI or state.
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
 * firing `onClose`. Presentation only beyond that context read; every colour /
 * space value resolves from `useTokens()` so light + dark fall out of the
 * console's ThemeProvider mode.
 */

import React from 'react'
import { useTokens, Text } from '../styles/primitives'
import { useHydraFlow } from '../context/HydraFlowContext'
import { SystemPanel } from '../components/SystemPanel'

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
      aria-label="System configuration"
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
          <Text size="sm" weight="bold" uppercase>System configuration</Text>
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
        <div style={styles.body}>
          <SystemPanel
            backgroundWorkers={backgroundWorkers}
            onToggleBgWorker={toggleBgWorker}
            onTriggerBgWorker={triggerBgWorker}
            onUpdateInterval={updateBgWorkerInterval}
            onUpdateWatchdogTimeout={updateBgWorkerWatchdogTimeout}
          />
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
