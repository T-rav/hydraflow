import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { RepoOverview, buildRepoSummaries } from '../RepoOverview'

// RepoOverview is the operator console's multi-repo portfolio (epic #10556,
// Task 9). It is a pure, prop-driven component: given a list of per-repo
// summaries (built by `buildRepoSummaries` from the aggregate socket state) and
// the `select(kind, value)` callback from `useOperatorSelection` (Task 2), it
// renders one row per repo — status dot, name, mini-pipeline counts, a
// "needs you" attention badge, a health dot, and last-activity — and drills into
// a repo via `select('repo', slug)` when a row is clicked. Single-repo installs
// skip the overview entirely (it renders nothing).

// A summary literal shaped exactly like `buildRepoSummaries(...)` output, so
// this component test is decoupled from the adapter internals.
function makeRepos(overrides) {
  return overrides ?? [
    {
      slug: 'acme/app',
      name: 'acme/app',
      running: true,
      counts: { triage: 1, plan: 0, implement: 2, review: 1, hitl: 0, merged: 5 },
      attention: { hitl: 0, failed: 1 },
      health: 'bad',
      lastActivity: '12:00:02',
    },
    {
      slug: 'acme/lib',
      name: 'acme/lib',
      running: false,
      counts: { triage: 0, plan: 0, implement: 0, review: 0, hitl: 2, merged: 3 },
      attention: { hitl: 2, failed: 0 },
      health: 'warn',
      lastActivity: '11:59:40',
    },
  ]
}

describe('RepoOverview', () => {
  it('renders one row per repo', () => {
    const { container } = render(<RepoOverview repos={makeRepos()} select={() => {}} />)
    const rows = container.querySelectorAll('[data-testid^="repo-row-"]')
    expect(rows).toHaveLength(2)
    expect(screen.getByTestId('repo-row-acme/app')).toBeInTheDocument()
    expect(screen.getByTestId('repo-row-acme/lib')).toBeInTheDocument()
  })

  it('renders the repo name and a status dot per row', () => {
    render(<RepoOverview repos={makeRepos()} select={() => {}} />)
    expect(screen.getByTestId('repo-row-acme/app')).toHaveTextContent('acme/app')
    expect(screen.getByTestId('repo-status-acme/app')).toHaveAttribute('data-running', 'true')
    expect(screen.getByTestId('repo-status-acme/lib')).toHaveAttribute('data-running', 'false')
  })

  it('renders mini-pipeline counts per repo', () => {
    render(<RepoOverview repos={makeRepos()} select={() => {}} />)
    const mini = screen.getByTestId('repo-mini-pipeline-acme/app')
    expect(mini).toBeInTheDocument()
    expect(screen.getByTestId('repo-mini-acme/app-implement')).toHaveTextContent('2')
    expect(screen.getByTestId('repo-mini-acme/app-merged')).toHaveTextContent('5')
    expect(screen.getByTestId('repo-mini-acme/lib-hitl')).toHaveTextContent('2')
  })

  it('shows a "needs you" attention badge with the hitl+failed total when non-zero', () => {
    render(<RepoOverview repos={makeRepos()} select={() => {}} />)
    // acme/app has 1 failed → badge "1"
    const appBadge = screen.getByTestId('repo-attention-acme/app')
    expect(appBadge).toHaveTextContent('1')
    // acme/lib has 2 hitl → badge "2"
    expect(screen.getByTestId('repo-attention-acme/lib')).toHaveTextContent('2')
  })

  it('omits the attention badge when a repo has nothing needing a human', () => {
    const repos = [
      {
        slug: 'clean/repo', name: 'clean/repo', running: true,
        counts: { triage: 0, plan: 0, implement: 1, review: 0, hitl: 0, merged: 0 },
        attention: { hitl: 0, failed: 0 }, health: 'ok', lastActivity: null,
      },
      {
        slug: 'other/repo', name: 'other/repo', running: true,
        counts: { triage: 0, plan: 0, implement: 0, review: 0, hitl: 0, merged: 1 },
        attention: { hitl: 0, failed: 0 }, health: 'ok', lastActivity: null,
      },
    ]
    render(<RepoOverview repos={repos} select={() => {}} />)
    expect(screen.queryByTestId('repo-attention-clean/repo')).toBeNull()
  })

  it('renders a health dot per row carrying the health state', () => {
    render(<RepoOverview repos={makeRepos()} select={() => {}} />)
    expect(screen.getByTestId('repo-health-acme/app')).toHaveAttribute('data-health', 'bad')
    expect(screen.getByTestId('repo-health-acme/lib')).toHaveAttribute('data-health', 'warn')
  })

  it('renders last-activity per row', () => {
    render(<RepoOverview repos={makeRepos()} select={() => {}} />)
    expect(screen.getByTestId('repo-activity-acme/app')).toHaveTextContent('12:00:02')
  })

  it('calls select("repo", slug) when a row is clicked', () => {
    const select = vi.fn()
    render(<RepoOverview repos={makeRepos()} select={select} />)
    fireEvent.click(screen.getByTestId('repo-row-acme/lib'))
    expect(select).toHaveBeenCalledWith('repo', 'acme/lib')
    expect(select).toHaveBeenCalledTimes(1)
  })

  it('single-repo installs skip the overview (renders nothing)', () => {
    const { container } = render(
      <RepoOverview repos={[makeRepos()[0]]} select={() => {}} />,
    )
    expect(container.querySelector('[data-testid="repo-overview"]')).toBeNull()
    expect(container.querySelectorAll('[data-testid^="repo-row-"]')).toHaveLength(0)
  })

  it('renders nothing for an empty repo list', () => {
    const { container } = render(<RepoOverview repos={[]} select={() => {}} />)
    expect(container.querySelector('[data-testid="repo-overview"]')).toBeNull()
  })
})

describe('buildRepoSummaries', () => {
  // A socket fixture shaped like the HydraFlowContext value in the aggregate
  // (repo=__all__) view: supervised repos + runtimes + a repo-tagged pipeline
  // snapshot + a repo-tagged event log (newest-first).
  function makeSocket(overrides = {}) {
    return {
      supervisedRepos: [
        { slug: 'acme/app', path: '/repos/acme/app', running: true },
        { slug: 'acme/lib', full_name: 'acme/lib', running: false },
      ],
      runtimes: [{ slug: 'acme/app', running: true }],
      pipelineIssues: {
        triage: [{ issue_number: 1, title: 'T', status: 'queued', repo: 'acme-app' }],
        plan: [],
        implement: [
          { issue_number: 2, title: 'B ok', status: 'active', repo: 'acme-app' },
          { issue_number: 3, title: 'B bad', status: 'failed', repo: 'acme-app' },
        ],
        review: [],
        hitl: [{ issue_number: 9, title: 'Stuck', status: 'hitl', repo: 'acme-lib' }],
        merged: [
          { issue_number: 4, title: 'M', status: 'merged', repo: 'acme-app' },
          { issue_number: 5, title: 'M2', status: 'merged', repo: 'acme-lib' },
        ],
      },
      events: [
        { type: 'transcript_line', timestamp: '2026-07-26T12:00:02Z', id: 3, repo: 'acme-app', data: {} },
        { type: 'transcript_line', timestamp: '2026-07-26T11:59:40Z', id: 2, repo: 'acme-lib', data: {} },
      ],
      ...overrides,
    }
  }

  it('produces one summary per supervised repo', () => {
    const summaries = buildRepoSummaries(makeSocket())
    expect(summaries).toHaveLength(2)
    expect(summaries.map(s => s.slug)).toEqual(['acme/app', 'acme/lib'])
  })

  it('derives mini-pipeline counts by filtering the aggregate snapshot per repo', () => {
    const [app, lib] = buildRepoSummaries(makeSocket())
    expect(app.counts.triage).toBe(1)
    expect(app.counts.implement).toBe(2)
    expect(app.counts.merged).toBe(1)
    expect(app.counts.hitl).toBe(0)
    // acme/lib only owns the hitl item and one merged item.
    expect(lib.counts.hitl).toBe(1)
    expect(lib.counts.merged).toBe(1)
    expect(lib.counts.implement).toBe(0)
  })

  it('aggregates attention (hitl + failed) per repo', () => {
    const [app, lib] = buildRepoSummaries(makeSocket())
    expect(app.attention.failed).toBe(1)
    expect(app.attention.hitl).toBe(0)
    expect(lib.attention.hitl).toBe(1)
    expect(lib.attention.failed).toBe(0)
  })

  it('marks running state from the runtime map, falling back to repo.running', () => {
    const [app, lib] = buildRepoSummaries(makeSocket())
    expect(app.running).toBe(true)
    expect(lib.running).toBe(false)
  })

  it('derives health: bad when a repo has failed items, warn when stopped, ok otherwise', () => {
    const [app, lib] = buildRepoSummaries(makeSocket())
    // acme/app is running but has a failed item → bad.
    expect(app.health).toBe('bad')
    // acme/lib is stopped, no failures → warn.
    expect(lib.health).toBe('warn')
    // A running, failure-free repo → ok.
    const [clean] = buildRepoSummaries(makeSocket({
      supervisedRepos: [{ slug: 'clean/repo', running: true }],
      runtimes: [{ slug: 'clean/repo', running: true }],
      pipelineIssues: { triage: [], plan: [], implement: [], review: [], hitl: [], merged: [] },
      events: [],
    }))
    expect(clean.health).toBe('ok')
  })

  it('reads last-activity from the newest repo-tagged event', () => {
    const [app, lib] = buildRepoSummaries(makeSocket())
    expect(app.lastActivity).toBe('2026-07-26T12:00:02Z')
    expect(lib.lastActivity).toBe('2026-07-26T11:59:40Z')
  })

  it('returns an empty list when there are no supervised repos', () => {
    expect(buildRepoSummaries({})).toEqual([])
    expect(buildRepoSummaries({ supervisedRepos: [] })).toEqual([])
  })
})
