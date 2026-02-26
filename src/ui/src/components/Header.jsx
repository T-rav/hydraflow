import React, { useState, useRef, useEffect } from 'react'
import { theme } from '../theme'
import { useHydraFlow } from '../context/HydraFlowContext'
import { PIPELINE_STAGES } from '../constants'

export function Header({
  connected, orchestratorStatus,
  onStart, onStop,
}) {
  const { stageStatus, config } = useHydraFlow()
  const workload = stageStatus.workload
  const hasActiveWorkers = workload.active > 0
  const appVersion = config?.app_version || ''
  const latestVersion = config?.latest_version || ''
  const updateAvailable = Boolean(config?.update_available && latestVersion)

  // Track minimum stopping duration to prevent flicker
  const [stoppingHeld, setStoppingHeld] = useState(false)
  const stoppingTimer = useRef(null)

  useEffect(() => {
    if (orchestratorStatus === 'stopping') {
      setStoppingHeld(true)
      if (stoppingTimer.current) clearTimeout(stoppingTimer.current)
    } else if (stoppingHeld) {
      stoppingTimer.current = setTimeout(() => {
        setStoppingHeld(false)
      }, 1500)
    }
    return () => {
      if (stoppingTimer.current) clearTimeout(stoppingTimer.current)
    }
  }, [orchestratorStatus]) // eslint-disable-line react-hooks/exhaustive-deps

  // Clear held state early when workers confirm idle and status is not stopping
  useEffect(() => {
    if (!hasActiveWorkers && orchestratorStatus !== 'stopping') {
      if (stoppingTimer.current) clearTimeout(stoppingTimer.current)
      setStoppingHeld(false)
    }
  }, [hasActiveWorkers, orchestratorStatus])

  const isStopping = orchestratorStatus === 'stopping' || stoppingHeld
  const canStart = (orchestratorStatus === 'idle' || orchestratorStatus === 'done' || orchestratorStatus === 'auth_failed') &&
    !stoppingHeld
  const isRunning = orchestratorStatus === 'running'
  const isCreditsPaused = orchestratorStatus === 'credits_paused'

  const sessionStages = PIPELINE_STAGES.map((stage) => ({
    key: stage.key,
    label: stage.label,
    color: stage.color,
    count: stageStatus?.[stage.key]?.sessionCount || 0,
  }))

  const abbreviateStage = (label) => {
    if (label.length <= 4) return label.toUpperCase()
    return label.slice(0, 3).toUpperCase()
  }

  return (
    <header style={styles.header}>
      <div style={styles.left}>
        <img src="/hydraflow-logo-small.png" alt="HydraFlow" style={styles.logoImg} />
        <div style={styles.logoGroup}>
          <span style={styles.logo}>HYDRAFLOW</span>
          <span style={styles.subtitle}>Intent in.</span>
          <span style={styles.subtitle}>Software out.</span>
          {appVersion && <span style={styles.version}>v{appVersion}</span>}
          {updateAvailable && (
            <span style={styles.updateNotice}>
              Update available: v{latestVersion} (`hf check-update`)
            </span>
          )}
        </div>
        <span style={connected ? dotConnected : dotDisconnected} />
      </div>
      <div style={styles.center}>
        <div style={styles.sessionBox}>
          <span style={styles.sessionLabel}>Session</span>
          <div style={styles.workload}>
            <span style={styles.workloadActive}>{workload.active} active</span>
            <span style={styles.workloadSep}>|</span>
            <span style={styles.workloadDone}>{workload.done} done</span>
            <span style={styles.workloadSep}>|</span>
            <span style={styles.workloadFailed}>{workload.failed} failed</span>
            <span style={styles.workloadSep}>|</span>
            <span>{workload.total} total</span>
          </div>
          <div style={styles.pipelineRow} data-testid="session-pipeline">
            {sessionStages.map((stage, index) => (
              <React.Fragment key={stage.key}>
                <div
                  style={{ ...styles.pipelineStage, borderColor: stage.color }}
                  data-testid={`session-stage-${stage.key}`}
                >
                  <span style={{ ...styles.pipelineLabel, color: stage.color }}>
                    {abbreviateStage(stage.label)}
                  </span>
                  <span style={styles.pipelineValue}>{stage.count}</span>
                </div>
                {index < sessionStages.length - 1 && (
                  <span style={styles.pipelineArrow}>→</span>
                )}
              </React.Fragment>
            ))}
          </div>
        </div>
      </div>
      <div style={styles.controls}>
        {canStart && (
          <button
            style={connected ? startBtnEnabled : startBtnDisabled}
            onClick={onStart}
            disabled={!connected}
          >
            Start
          </button>
        )}
        {isRunning && (
          <button style={styles.stopBtn} onClick={onStop}>
            Stop
          </button>
        )}
        {isCreditsPaused && (
          <>
            <span style={styles.creditsPausedBadge}>Credits Paused</span>
            <button style={styles.stopBtn} onClick={onStop}>
              Stop
            </button>
          </>
        )}
        {isStopping && (
          <span style={styles.stoppingBadge}>
            Stopping…
          </span>
        )}
      </div>
    </header>
  )
}

const styles = {
  header: {
    gridColumn: '1 / -1',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '20px 20px',
    background: theme.surface,
    borderBottom: `1px solid ${theme.border}`,
  },
  left: { display: 'flex', alignItems: 'flex-end', gap: 8, flexShrink: 0 },
  logoImg: { height: 56, width: 'auto' },
  logoGroup: { display: 'flex', flexDirection: 'column' },
  logo: { fontSize: 18, fontWeight: 700, color: theme.accent },
  subtitle: { color: theme.textMuted, fontWeight: 400, fontSize: 12 },
  version: { color: theme.textMuted, fontWeight: 500, fontSize: 11 },
  updateNotice: { color: theme.accent, fontWeight: 600, fontSize: 11 },
  dot: { width: 8, height: 8, borderRadius: '50%', display: 'inline-block' },
  center: {
    display: 'flex',
    alignItems: 'center',
    gap: 14,
    minWidth: 0,
    overflow: 'hidden',
  },
  sessionBox: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'flex-start',
    gap: 6,
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    padding: '8px 14px',
    background: theme.bg,
  },
  sessionLabel: {
    color: theme.textMuted,
    fontSize: 13,
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
  },
  workload: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    fontSize: 12,
    color: theme.textMuted,
    flexWrap: 'wrap',
  },
  pipelineRow: {
    display: 'flex',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: 6,
  },
  pipelineStage: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    borderRadius: 999,
    padding: '2px 8px',
    border: `1px solid ${theme.border}`,
    background: theme.surface,
  },
  pipelineLabel: {
    fontSize: 10,
    fontWeight: 600,
    letterSpacing: '0.5px',
    color: theme.textMuted,
  },
  pipelineValue: {
    fontSize: 13,
    fontWeight: 700,
    color: theme.textBright,
  },
  pipelineArrow: {
    color: theme.textMuted,
    fontSize: 12,
    fontWeight: 600,
  },
  workloadSep: { color: theme.border },
  workloadActive: { color: theme.accent },
  workloadDone: { color: theme.green },
  workloadFailed: { color: theme.red },
  controls: { display: 'flex', alignItems: 'center', gap: 10, marginLeft: 10, flexShrink: 0 },
  startBtn: {
    padding: '4px 14px',
    borderRadius: 6,
    border: 'none',
    background: theme.btnGreen,
    color: theme.white,
    fontSize: 12,
    fontWeight: 600,
    cursor: 'pointer',
  },
  stopBtn: {
    padding: '4px 14px',
    borderRadius: 6,
    border: 'none',
    background: theme.btnRed,
    color: theme.white,
    fontSize: 12,
    fontWeight: 600,
    cursor: 'pointer',
  },
  stoppingBadge: {
    padding: '4px 12px',
    borderRadius: 6,
    background: theme.yellow,
    color: theme.bg,
    fontSize: 12,
    fontWeight: 600,
  },
  creditsPausedBadge: {
    padding: '4px 12px',
    borderRadius: 6,
    background: theme.yellow,
    color: theme.bg,
    fontSize: 12,
    fontWeight: 600,
  },
}

// Pre-computed connection dot variants
export const dotConnected = { ...styles.dot, background: theme.green }
export const dotDisconnected = { ...styles.dot, background: theme.red }

// Pre-computed start button variants
export const startBtnEnabled = { ...styles.startBtn, opacity: 1, cursor: 'pointer' }
export const startBtnDisabled = { ...styles.startBtn, opacity: 0.4, cursor: 'not-allowed' }
