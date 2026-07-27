/**
 * RepoOverview — the operator console's multi-repo portfolio (epic #10556, Task 9).
 *
 * When HydraFlow supervises more than one repo, the operator lands on a
 * portfolio: one row per repo with a status dot (runtime up/down), the repo
 * name, a mini-pipeline count strip, a "needs you" attention badge (HITL +
 * failed depth), a health dot, and last-activity. Clicking a row drills into
 * that repo via `select('repo', slug)` (Task-2 selection hook), which the
 * console turns into the single-repo pipeline view. Single-repo installs skip
 * the overview entirely — the component renders nothing so the console shows the
 * pipeline directly.
 *
 * This component is pure and prop-driven (no socket, no context): it consumes a
 * list of per-repo summaries built by {@link buildRepoSummaries} from the
 * aggregate (repo=__all__) socket state. Keeping the derivation in an exported
 * pure adapter mirrors the Task-1 view-model pattern and keeps both halves
 * independently testable. Styling uses the shared `theme` CSS-variable refs so
 * the dark/light paths (and the Phase-2 token migration) keep working.
 */

import React from 'react'
import { theme } from '../theme'
import { canonicalRepoSlug } from '../constants'
import { buildDisplayName } from '../components/RepoSelector'
import { OPERATOR_STAGES, toPipeline } from './model/pipeline'

// ---------------------------------------------------------------------------
// Pure adapter: aggregate socket state → per-repo summaries.
// ---------------------------------------------------------------------------

/**
 * Build the per-repo portfolio summaries from the aggregate socket state.
 *
 * Under the aggregate (repo=__all__) view the pipeline snapshot carries every
 * repo's issues, each tagged with its `repo` slug, and the event log is
 * repo-tagged too — so a single fetch already contains everything the portfolio
 * needs; no backend change and no per-repo fetch. For each supervised repo we
 * filter the aggregate snapshot down to that repo and reuse `toPipeline(...)`
 * (Task 1) to derive its mini view model, then fold the per-stage attention into
 * a single (hitl, failed) pair and pick a health/last-activity signal.
 *
 * @param {object} socket - HydraFlow context value (supervisedRepos, runtimes,
 *   pipelineIssues, events).
 * @returns {Array<{slug,name,running,counts,attention,health,lastActivity}>}
 */
export function buildRepoSummaries(socket = {}) {
  const repos = Array.isArray(socket.supervisedRepos) ? socket.supervisedRepos : []
  if (repos.length === 0) return []

  const runtimes = Array.isArray(socket.runtimes) ? socket.runtimes : []
  const runtimeMap = new Map(runtimes.map(rt => [canonicalRepoSlug(rt.slug), rt]))
  const pipelineIssues = socket.pipelineIssues || {}
  const events = Array.isArray(socket.events) ? socket.events : []

  return repos.map((repo, index) => {
    const rawSlug = repo.slug || repo.repo || repo.full_name || repo.path || `repo-${index + 1}`
    const canonical = canonicalRepoSlug(rawSlug)
    const runtime = runtimeMap.get(canonical)
    const running = Boolean(runtime?.running ?? repo.running ?? repo.status === 'running')

    // Filter the aggregate snapshot down to this repo, then reuse toPipeline.
    const perRepoStages = {}
    for (const { key } of OPERATOR_STAGES) {
      const raw = pipelineIssues[key] || []
      perRepoStages[key] = raw.filter(i => canonicalRepoSlug(i?.repo) === canonical)
    }
    const mini = toPipeline({ stages: perRepoStages })

    const counts = {}
    let hitl = 0
    let failed = 0
    for (const stage of mini.stages) {
      counts[stage.key] = stage.count
      hitl += stage.attention.hitl
      failed += stage.attention.failed
    }

    // Health: a failing pipeline is bad; a stopped runtime warrants a warn even
    // when idle; a running, failure-free repo is ok.
    const health = failed > 0 ? 'bad' : running ? 'ok' : 'warn'

    // Newest repo-tagged event (events are stored newest-first).
    const lastEvent = events.find(e => canonicalRepoSlug(e?.repo) === canonical)
    const lastActivity = lastEvent?.timestamp ?? null

    return {
      slug: rawSlug,
      name: buildDisplayName(repo),
      running,
      counts,
      attention: { hitl, failed },
      health,
      lastActivity,
    }
  })
}

// ---------------------------------------------------------------------------
// Presentation.
// ---------------------------------------------------------------------------

const HEALTH_COLOR = {
  ok: theme.green,
  warn: theme.yellow,
  bad: theme.red,
}

const styles = {
  wrapper: {
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    background: theme.surface,
    padding: 8,
    minWidth: 0,
  },
  heading: {
    fontSize: 11,
    fontWeight: 700,
    textTransform: 'uppercase',
    letterSpacing: 0.4,
    color: theme.textMuted,
    padding: '2px 4px',
  },
  row: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    width: '100%',
    textAlign: 'left',
    border: `1px solid ${theme.border}`,
    borderRadius: 6,
    background: theme.surfaceInset,
    color: theme.text,
    cursor: 'pointer',
    padding: '8px 10px',
    minWidth: 0,
  },
  statusDot: {
    width: 8,
    height: 8,
    borderRadius: '50%',
    flexShrink: 0,
  },
  nameCol: {
    display: 'flex',
    flexDirection: 'column',
    gap: 2,
    minWidth: 0,
    flex: '1 1 auto',
  },
  name: {
    fontSize: 13,
    fontWeight: 700,
    color: theme.textBright,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  activity: {
    fontSize: 10,
    color: theme.textMuted,
    fontVariantNumeric: 'tabular-nums',
  },
  mini: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    fontSize: 11,
    color: theme.textMuted,
    fontVariantNumeric: 'tabular-nums',
    flexShrink: 0,
  },
  miniCell: {
    display: 'inline-flex',
    alignItems: 'baseline',
    gap: 2,
  },
  miniKey: {
    fontSize: 9,
    textTransform: 'uppercase',
    color: theme.textInactive,
  },
  miniVal: {
    fontWeight: 700,
    color: theme.text,
  },
  attention: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 4,
    borderRadius: 999,
    padding: '2px 8px',
    fontSize: 10,
    fontWeight: 800,
    color: theme.orange,
    border: `1px solid ${theme.orange}`,
    background: theme.orangeSubtle,
    whiteSpace: 'nowrap',
    flexShrink: 0,
  },
  healthDot: {
    width: 10,
    height: 10,
    borderRadius: '50%',
    flexShrink: 0,
  },
}

// Short mini-pipeline labels, in lifecycle order.
const MINI_LABEL = {
  triage: 'T',
  plan: 'P',
  implement: 'B',
  review: 'R',
  hitl: 'H',
  merged: 'M',
}

/**
 * @param {{
 *   repos?: Array<object>,   // buildRepoSummaries(...) output
 *   select?: (kind: string, value: unknown) => void,
 * }} props
 */
export function RepoOverview({ repos = [], select = () => {} }) {
  // Single-repo (or empty) installs skip the overview entirely.
  if (!Array.isArray(repos) || repos.length <= 1) return null

  return (
    <div data-testid="repo-overview" style={styles.wrapper}>
      <div style={styles.heading}>Repositories</div>
      {repos.map(repo => {
        const attentionTotal = (repo.attention?.hitl ?? 0) + (repo.attention?.failed ?? 0)
        const health = repo.health ?? 'ok'
        return (
          <button
            type="button"
            key={repo.slug}
            data-testid={`repo-row-${repo.slug}`}
            style={styles.row}
            onClick={() => select('repo', repo.slug)}
          >
            <span
              data-testid={`repo-status-${repo.slug}`}
              data-running={String(!!repo.running)}
              title={repo.running ? 'Running' : 'Stopped'}
              style={{ ...styles.statusDot, background: repo.running ? theme.green : theme.textMuted }}
            />
            <span style={styles.nameCol}>
              <span style={styles.name}>{repo.name}</span>
              <span data-testid={`repo-activity-${repo.slug}`} style={styles.activity}>
                {repo.lastActivity ? repo.lastActivity : 'no activity'}
              </span>
            </span>

            <span data-testid={`repo-mini-pipeline-${repo.slug}`} style={styles.mini}>
              {OPERATOR_STAGES.map(({ key }) => (
                <span key={key} style={styles.miniCell} title={key}>
                  <span style={styles.miniKey}>{MINI_LABEL[key]}</span>
                  <span data-testid={`repo-mini-${repo.slug}-${key}`} style={styles.miniVal}>
                    {repo.counts?.[key] ?? 0}
                  </span>
                </span>
              ))}
            </span>

            {attentionTotal > 0 && (
              <span
                data-testid={`repo-attention-${repo.slug}`}
                style={styles.attention}
                title={`${repo.attention?.hitl ?? 0} HITL · ${repo.attention?.failed ?? 0} failed`}
              >
                needs you {attentionTotal}
              </span>
            )}

            <span
              data-testid={`repo-health-${repo.slug}`}
              data-health={health}
              title={`health: ${health}`}
              style={{ ...styles.healthDot, background: HEALTH_COLOR[health] ?? theme.textMuted }}
            />
          </button>
        )
      })}
    </div>
  )
}

export default RepoOverview
