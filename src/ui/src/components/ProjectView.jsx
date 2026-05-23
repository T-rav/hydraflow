import React, { useCallback, useEffect, useState } from 'react'
import { useHydraFlow } from '../context/HydraFlowContext'
import { theme } from '../theme'

function readPlanProgress(project) {
  const progress = project?.plan_progress || project?.onboarding_plan_progress
  if (progress && Number.isFinite(Number(progress.completed)) && Number.isFinite(Number(progress.total))) {
    return {
      completed: Number(progress.completed),
      total: Number(progress.total),
    }
  }
  const planDraft = project?.onboarding_plan_draft || project?.plan_draft
  if (Array.isArray(planDraft)) {
    return { completed: 0, total: planDraft.length }
  }
  return { completed: 0, total: 0 }
}

function readCurrentPlan(project) {
  return project?.current_plan || project?.onboarding_current_plan || project?.plan || 'Plan 01'
}

export function ProjectView({ project }) {
  const { continueOnboardingPlan, pushOnboardingDraft, upgradeOnboardingFormat } = useHydraFlow()
  const [activityOpen, setActivityOpen] = useState(false)
  const [pushState, setPushState] = useState('idle')
  const [pushError, setPushError] = useState('')
  const [continueState, setContinueState] = useState('idle')
  const [continueError, setContinueError] = useState('')
  const [upgradeState, setUpgradeState] = useState('idle')
  const [upgradeError, setUpgradeError] = useState('')
  const [activityEvents, setActivityEvents] = useState(project?.onboarding_events || [])

  useEffect(() => {
    setActivityEvents(project?.onboarding_events || [])
  }, [project?.onboarding_events])

  const handlePush = useCallback(async () => {
    if (!project?.onboarding_draft_id || pushState === 'running') return
    setPushState('running')
    setPushError('')
    const result = await pushOnboardingDraft?.(project.onboarding_draft_id, {
      onActivity: (event) => {
        setActivityEvents(prev => [...prev, event])
      },
    })
    if (!result?.ok) {
      setPushState('failed')
      setPushError(result?.error || 'Push failed')
      setActivityOpen(true)
      return
    }
    setPushState('succeeded')
  }, [project?.onboarding_draft_id, pushOnboardingDraft, pushState])

  const handleContinuePlan = useCallback(async () => {
    if (!project?.onboarding_draft_id || continueState === 'running') return
    setContinueState('running')
    setContinueError('')
    const result = await continueOnboardingPlan?.(project.onboarding_draft_id, {
      current_plan: readCurrentPlan(project),
    })
    if (!result?.ok) {
      setContinueState('failed')
      setContinueError(result?.error || 'Continue plan failed')
      setActivityOpen(true)
      return
    }
    setContinueState('succeeded')
  }, [continueOnboardingPlan, continueState, project])

  const handleUpgradeFormat = useCallback(async () => {
    if (!project?.onboarding_draft_id || upgradeState === 'running') return
    setUpgradeState('running')
    setUpgradeError('')
    const result = await upgradeOnboardingFormat?.(project.onboarding_draft_id)
    if (!result?.ok) {
      setUpgradeState('failed')
      setUpgradeError(result?.error || 'Format upgrade failed')
      setActivityOpen(true)
      return
    }
    setUpgradeState('succeeded')
  }, [project?.onboarding_draft_id, upgradeOnboardingFormat, upgradeState])

  if (!project) return null

  const events = activityEvents || []
  const canPush = Boolean(project.onboarding_draft_id) && pushState !== 'running'
  const progress = readPlanProgress(project)
  const currentPlan = readCurrentPlan(project)
  const planComplete = progress.total > 0 && progress.completed >= progress.total
  const showContinue = project.continue_plan_available === true || planComplete
  const canContinue = Boolean(project.onboarding_draft_id) && continueState !== 'running'
  const showUpgrade = project.upgrade_available === true || project.format_upgrade_available === true
  const canUpgrade = Boolean(project.onboarding_draft_id) && upgradeState !== 'running'
  const repoStatus = project.local_only
    ? pushState === 'failed' ? 'Push failed' : pushState === 'succeeded' ? 'Pushed' : 'Ready locally'
    : project.status === 'running' || project.running || project.pipeline_enabled ? 'Factory pipeline active' : 'Factory repo selected'

  return (
    <div style={project.local_only ? styles.wrapperLocal : styles.wrapper} data-testid={project.local_only ? 'project-view-local-only' : 'project-view'}>
      <div style={styles.header}>
        <div style={styles.titleBlock}>
          <span style={project.local_only ? styles.badgeLocal : styles.badge}>{project.local_only ? 'local only' : 'selected repo'}</span>
          <span style={styles.name}>{project.full_name || project.slug || project.path}</span>
          {project.path && <span style={styles.path}>{project.path}</span>}
        </div>
        <div style={styles.actions}>
          {showContinue && (
            <button
              type="button"
              style={canContinue ? styles.secondaryAction : styles.secondaryDisabled}
              disabled={!canContinue}
              onClick={handleContinuePlan}
              title={canContinue ? undefined : 'Waiting for onboarding draft state'}
            >
              {continueState === 'running' ? 'Continuing...' : continueState === 'succeeded' ? 'Plan continued' : 'Continue to next plan'}
            </button>
          )}
          {showUpgrade && (
            <button
              type="button"
              style={canUpgrade ? styles.secondaryAction : styles.secondaryDisabled}
              disabled={!canUpgrade}
              onClick={handleUpgradeFormat}
              title={canUpgrade ? undefined : 'Waiting for onboarding draft state'}
            >
              {upgradeState === 'running' ? 'Upgrading...' : upgradeState === 'succeeded' ? 'Upgrade PR opened' : 'Upgrade format'}
            </button>
          )}
          {project.local_only && (
            <button
              type="button"
              style={canPush ? styles.pushButton : styles.pushDisabled}
              disabled={!canPush}
              onClick={handlePush}
              title={canPush ? undefined : 'Waiting for onboarding draft state'}
            >
              {pushState === 'running' ? 'Pushing...' : 'Push to GitHub'}
            </button>
          )}
        </div>
      </div>
      <div style={styles.planRow}>
        <span style={styles.planPill}>{currentPlan}</span>
        <span style={styles.planText}>{progress.completed}/{progress.total} issues complete</span>
      </div>
      <div style={styles.statusRow}>
        <span style={pushState === 'failed' ? styles.statusDotFailed : styles.statusDot} />
        <span>{repoStatus}</span>
        {(project.local_only || events.length > 0) && (
          <button type="button" style={styles.activityButton} onClick={() => setActivityOpen(prev => !prev)}>
            Activity {activityOpen ? 'up' : 'down'}
          </button>
        )}
      </div>
      {pushError && <div style={styles.error}>{pushError}</div>}
      {continueError && <div style={styles.error}>{continueError}</div>}
      {upgradeError && <div style={styles.error}>{upgradeError}</div>}
      {activityOpen && (
        <div style={styles.activityLog} data-testid="project-activity-log">
          {events.length === 0 ? (
            <span style={styles.muted}>No onboarding activity recorded</span>
          ) : events.map((event, index) => (
            <div key={`${event.message}-${index}`} style={event.level === 'error' ? styles.eventError : styles.event}>
              {event.message}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

const styles = {
  wrapper: {
    border: `1px solid ${theme.border}`,
    background: theme.surface,
    borderRadius: 8,
    padding: 12,
    marginBottom: 12,
  },
  wrapperLocal: {
    border: `1px solid ${theme.orange}`,
    background: theme.orangeSubtle,
    borderRadius: 8,
    padding: 12,
    marginBottom: 12,
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    gap: 12,
    alignItems: 'flex-start',
  },
  titleBlock: {
    display: 'flex',
    flexDirection: 'column',
    gap: 4,
    minWidth: 0,
  },
  badge: {
    alignSelf: 'flex-start',
    color: theme.accent,
    border: `1px solid ${theme.accent}`,
    borderRadius: 999,
    padding: '2px 7px',
    fontSize: 10,
    fontWeight: 700,
    textTransform: 'uppercase',
  },
  badgeLocal: {
    alignSelf: 'flex-start',
    color: theme.orange,
    border: `1px solid ${theme.orange}`,
    borderRadius: 999,
    padding: '2px 7px',
    fontSize: 10,
    fontWeight: 700,
    textTransform: 'uppercase',
  },
  name: {
    color: theme.textBright,
    fontSize: 14,
    fontWeight: 700,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  path: {
    color: theme.textMuted,
    fontSize: 11,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  pushButton: {
    border: `1px solid ${theme.orange}`,
    borderRadius: 6,
    background: theme.orange,
    color: theme.white,
    padding: '7px 10px',
    fontSize: 12,
    fontWeight: 700,
    cursor: 'pointer',
    flexShrink: 0,
  },
  pushDisabled: {
    border: `1px solid ${theme.border}`,
    borderRadius: 6,
    background: theme.surfaceInset,
    color: theme.textMuted,
    padding: '7px 10px',
    fontSize: 12,
    fontWeight: 700,
    cursor: 'not-allowed',
    flexShrink: 0,
  },
  actions: {
    display: 'flex',
    gap: 8,
    flexWrap: 'wrap',
    justifyContent: 'flex-end',
  },
  secondaryAction: {
    border: `1px solid ${theme.accent}`,
    borderRadius: 6,
    background: theme.surface,
    color: theme.accent,
    padding: '7px 10px',
    fontSize: 12,
    fontWeight: 700,
    cursor: 'pointer',
    flexShrink: 0,
  },
  secondaryDisabled: {
    border: `1px solid ${theme.border}`,
    borderRadius: 6,
    background: theme.surfaceInset,
    color: theme.textMuted,
    padding: '7px 10px',
    fontSize: 12,
    fontWeight: 700,
    cursor: 'not-allowed',
    flexShrink: 0,
  },
  planRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    marginTop: 10,
    flexWrap: 'wrap',
  },
  planPill: {
    border: `1px solid ${theme.border}`,
    borderRadius: 999,
    color: theme.textBright,
    background: theme.surfaceInset,
    padding: '2px 8px',
    fontSize: 11,
    fontWeight: 700,
  },
  planText: {
    color: theme.text,
    fontSize: 12,
  },
  statusRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    marginTop: 10,
    color: theme.text,
    fontSize: 12,
  },
  statusDot: {
    width: 8,
    height: 8,
    borderRadius: '50%',
    background: theme.orange,
    flexShrink: 0,
  },
  statusDotFailed: {
    width: 8,
    height: 8,
    borderRadius: '50%',
    background: theme.red,
    flexShrink: 0,
  },
  error: {
    marginTop: 8,
    color: theme.red,
    fontSize: 12,
    fontWeight: 600,
  },
  activityButton: {
    marginLeft: 'auto',
    border: 'none',
    background: 'transparent',
    color: theme.accent,
    fontSize: 12,
    fontWeight: 700,
    cursor: 'pointer',
  },
  activityLog: {
    marginTop: 10,
    background: theme.surfaceInset,
    border: `1px solid ${theme.border}`,
    borderRadius: 6,
    padding: 10,
    maxHeight: 140,
    overflowY: 'auto',
  },
  event: {
    color: theme.text,
    fontSize: 12,
    padding: '3px 0',
  },
  eventError: {
    color: theme.red,
    fontSize: 12,
    padding: '3px 0',
  },
  muted: {
    color: theme.textMuted,
    fontSize: 12,
  },
}
