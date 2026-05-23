import React, { useCallback, useState } from 'react'
import { useHydraFlow } from '../context/HydraFlowContext'
import { theme } from '../theme'

export function ProjectView({ project }) {
  const { pushOnboardingDraft } = useHydraFlow()
  const [activityOpen, setActivityOpen] = useState(false)
  const [pushState, setPushState] = useState('idle')
  const [pushError, setPushError] = useState('')

  const handlePush = useCallback(async () => {
    if (!project?.onboarding_draft_id || pushState === 'running') return
    setPushState('running')
    setPushError('')
    const result = await pushOnboardingDraft?.(project.onboarding_draft_id)
    if (!result?.ok) {
      setPushState('failed')
      setPushError(result?.error || 'Push failed')
      setActivityOpen(true)
      return
    }
    setPushState('succeeded')
  }, [project?.onboarding_draft_id, pushOnboardingDraft, pushState])

  if (!project?.local_only) return null

  const events = project.onboarding_events || []
  const canPush = Boolean(project.onboarding_draft_id) && pushState !== 'running'

  return (
    <div style={styles.wrapper} data-testid="project-view-local-only">
      <div style={styles.header}>
        <div style={styles.titleBlock}>
          <span style={styles.badge}>local only</span>
          <span style={styles.name}>{project.full_name || project.slug || project.path}</span>
          {project.path && <span style={styles.path}>{project.path}</span>}
        </div>
        <button
          type="button"
          style={canPush ? styles.pushButton : styles.pushDisabled}
          disabled={!canPush}
          onClick={handlePush}
          title={canPush ? undefined : 'Waiting for onboarding draft state'}
        >
          {pushState === 'running' ? 'Pushing...' : 'Push to GitHub'}
        </button>
      </div>
      <div style={styles.statusRow}>
        <span style={pushState === 'failed' ? styles.statusDotFailed : styles.statusDot} />
        <span>{pushState === 'failed' ? 'Push failed' : pushState === 'succeeded' ? 'Pushed' : 'Ready locally'}</span>
        <button type="button" style={styles.activityButton} onClick={() => setActivityOpen(prev => !prev)}>
          Activity {activityOpen ? 'up' : 'down'}
        </button>
      </div>
      {pushError && <div style={styles.error}>{pushError}</div>}
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
