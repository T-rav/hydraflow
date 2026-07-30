import { describe, it, expect } from 'vitest'
import { toTimeline } from '../timeline'

// `toTimeline` folds the raw event stream into chronological PHASE CONTAINERS,
// segmented by `phase_change` boundaries. Input is newest-first (as the
// HydraFlowContext reducer stores it); output is oldest-first. The clock is
// injected via `now` so the open phase's duration is deterministic.
//
// Event shapes are verbatim from the live WS stream:
//   phase_change → { phase, issue? }   (issue is optional — global phase signal)
//   transcript_line → { issue, line }
//   pr_created → { pr, issue, url, title, branch }   (NO diff detail in stream)
//   merge_update → { pr, status, issue }
//   review_update → { pr, issue, verdict }

const ev = (type, data, id, ts) => ({ type, timestamp: ts, id, data })

// Build a newest-first event array (as the reducer stores) from an oldest-first
// authoring order — the model reverses + stable-sorts by ts internally.
const feed = (oldestFirst) => [...oldestFirst].reverse()

// A canonical single-issue lifecycle: triage → plan → build → review, with one
// event per phase and a PR opened during build.
const lifecycle = () => feed([
  ev('phase_change', { phase: 'triage', issue: 10812 }, 1, '2026-07-26T12:00:00Z'),
  ev('transcript_line', { issue: 10812, line: 'labeled hydraflow-ready' }, 2, '2026-07-26T12:00:05Z'),
  ev('phase_change', { phase: 'plan', issue: 10812 }, 3, '2026-07-26T12:02:00Z'),
  ev('transcript_line', { issue: 10812, line: 'plan posted' }, 4, '2026-07-26T12:02:30Z'),
  ev('phase_change', { phase: 'implement', issue: 10812 }, 5, '2026-07-26T12:05:00Z'),
  ev('pr_created', { pr: 10820, issue: 10812, url: 'https://gh/x/y/pull/10820', title: 'feat: add X', branch: 'feat/x' }, 6, '2026-07-26T12:10:00Z'),
  ev('phase_change', { phase: 'review', issue: 10812 }, 7, '2026-07-26T12:17:00Z'),
  ev('review_update', { pr: 10820, issue: 10812, verdict: 'request-changes' }, 8, '2026-07-26T12:18:00Z'),
])

const NOW = Date.parse('2026-07-26T12:21:00Z')

describe('toTimeline — segmentation', () => {
  it('segments the stream into one container per phase_change, oldest-first', () => {
    const { entries } = toTimeline(lifecycle(), { now: NOW })
    expect(entries.map(e => e.phase)).toEqual(['triage', 'plan', 'implement', 'review'])
  })

  it('maps the implement phase to the Build label + implement stage key', () => {
    const { entries } = toTimeline(lifecycle(), { now: NOW })
    const build = entries.find(e => e.phase === 'implement')
    expect(build.phaseLabel).toBe('Build')
  })

  it('assigns each non-boundary event to its open phase container', () => {
    const { entries } = toTimeline(lifecycle(), { now: NOW })
    const [triage, plan, build, review] = entries
    expect(triage.events.map(r => r.text)).toEqual(['labeled hydraflow-ready'])
    expect(plan.events.map(r => r.text)).toEqual(['plan posted'])
    expect(build.events.map(r => r.text)).toEqual(['PR #10820 opened'])
    expect(review.events).toHaveLength(1)
  })

  it('reuses summarizeEvent for event text (event bullets read like the activity feed)', () => {
    const { entries } = toTimeline(lifecycle(), { now: NOW })
    const review = entries.find(e => e.phase === 'review')
    expect(review.events[0].text).toContain('10820')
  })

  it('attaches the issue from the phase_change payload', () => {
    const { entries } = toTimeline(lifecycle(), { now: NOW })
    expect(entries.every(e => e.issue === 10812)).toBe(true)
  })

  it('infers the container issue from contained events when phase_change carries none', () => {
    const events = feed([
      ev('phase_change', { phase: 'implement' }, 1, '2026-07-26T12:00:00Z'),
      ev('transcript_line', { issue: 501, line: 'a' }, 2, '2026-07-26T12:00:10Z'),
    ])
    const { entries } = toTimeline(events, { now: NOW })
    expect(entries).toHaveLength(1)
    expect(entries[0].issue).toBe(501)
  })

  it('drops events that arrive before the first phase_change (no phase context)', () => {
    const events = feed([
      ev('transcript_line', { issue: 7, line: 'orphan' }, 1, '2026-07-26T12:00:00Z'),
      ev('phase_change', { phase: 'triage', issue: 7 }, 2, '2026-07-26T12:00:10Z'),
      ev('transcript_line', { issue: 7, line: 'kept' }, 3, '2026-07-26T12:00:20Z'),
    ])
    const { entries } = toTimeline(events, { now: NOW })
    expect(entries).toHaveLength(1)
    expect(entries[0].events.map(r => r.text)).toEqual(['kept'])
  })
})

describe('toTimeline — duration from injected now', () => {
  it('computes a closed phase duration from its start to the next boundary', () => {
    const { entries } = toTimeline(lifecycle(), { now: NOW })
    // triage 12:00:00 → plan boundary 12:02:00
    expect(entries[0].durationLabel).toBe('2m')
    // plan 12:02:00 → implement boundary 12:05:00
    expect(entries[1].durationLabel).toBe('3m')
    // implement 12:05:00 → review boundary 12:17:00
    expect(entries[2].durationLabel).toBe('12m')
  })

  it('measures the open (last) phase against the injected now', () => {
    const { entries } = toTimeline(lifecycle(), { now: NOW })
    // review 12:17:00 → now 12:21:00
    const review = entries[3]
    expect(review.endTs).toBeNull()
    expect(review.durationLabel).toBe('4m')
  })

  it('never reads the wall clock — the open phase has no duration when now is omitted', () => {
    const { entries } = toTimeline(lifecycle())
    // Closed phases still resolve (they have a concrete endTs)...
    expect(entries[0].durationLabel).toBe('2m')
    // ...but the open phase can't be measured without an injected clock.
    expect(entries[3].durationLabel).toBe('')
  })
})

describe('toTimeline — diff extraction (graceful degradation)', () => {
  it('surfaces a pr_created as a diff row carrying the PR number + url', () => {
    const { entries } = toTimeline(lifecycle(), { now: NOW })
    const build = entries.find(e => e.phase === 'implement')
    expect(build.diffs).toHaveLength(1)
    expect(build.diffs[0].prNumber).toBe(10820)
    expect(build.diffs[0].url).toBe('https://gh/x/y/pull/10820')
  })

  it('omits diff fields the event stream does not carry — never fabricated', () => {
    const { entries } = toTimeline(lifecycle(), { now: NOW })
    const diff = entries.find(e => e.phase === 'implement').diffs[0]
    // The live stream has no commit sha / file counts / line stats.
    expect(diff).not.toHaveProperty('commitSha')
    expect(diff).not.toHaveProperty('filesChanged')
    expect(diff).not.toHaveProperty('additions')
    expect(diff).not.toHaveProperty('deletions')
  })

  it('flows richer diff fields through defensively when a payload DOES carry them', () => {
    const events = feed([
      ev('phase_change', { phase: 'implement', issue: 1 }, 1, '2026-07-26T12:00:00Z'),
      ev('pr_created', {
        pr: 42, issue: 1, url: 'https://gh/pull/42',
        commit_sha: 'a1b2c3d4e5', files_changed: ['a.py', 'b.py'], additions: 42, deletions: 7,
      }, 2, '2026-07-26T12:01:00Z'),
    ])
    const diff = toTimeline(events, { now: NOW }).entries[0].diffs[0]
    expect(diff.prNumber).toBe(42)
    expect(diff.commitSha).toBe('a1b2c3d4e5')
    expect(diff.filesChanged).toBe(2)
    expect(diff.additions).toBe(42)
    expect(diff.deletions).toBe(7)
  })

  it('does not treat a review_update as a diff (it is an event bullet only)', () => {
    const { entries } = toTimeline(lifecycle(), { now: NOW })
    const review = entries.find(e => e.phase === 'review')
    expect(review.diffs).toHaveLength(0)
    expect(review.events).toHaveLength(1)
  })

  it('surfaces a merge_update as a diff row', () => {
    const events = feed([
      ev('phase_change', { phase: 'review', issue: 1 }, 1, '2026-07-26T12:00:00Z'),
      ev('merge_update', { pr: 99, status: 'merged', issue: 1 }, 2, '2026-07-26T12:01:00Z'),
    ])
    const diff = toTimeline(events, { now: NOW }).entries[0].diffs[0]
    expect(diff.prNumber).toBe(99)
  })
})

describe('toTimeline — item filter', () => {
  it('keeps every phase of the drilled issue', () => {
    const { entries } = toTimeline(lifecycle(), { item: 10812, now: NOW })
    expect(entries).toHaveLength(4)
    expect(entries.every(e => e.issue === 10812)).toBe(true)
  })

  it('returns no entries for an issue that never appears', () => {
    const { entries } = toTimeline(lifecycle(), { item: 99999, now: NOW })
    expect(entries).toEqual([])
  })

  it('narrows a mixed-issue phase container to just the requested issue', () => {
    const events = feed([
      ev('phase_change', { phase: 'implement' }, 1, '2026-07-26T12:00:00Z'),
      ev('transcript_line', { issue: 501, line: 'for 501' }, 2, '2026-07-26T12:00:10Z'),
      ev('transcript_line', { issue: 502, line: 'for 502' }, 3, '2026-07-26T12:00:20Z'),
    ])
    const { entries } = toTimeline(events, { item: 502, now: NOW })
    expect(entries).toHaveLength(1)
    expect(entries[0].issue).toBe(502)
    expect(entries[0].events.map(r => r.text)).toEqual(['for 502'])
  })
})

describe('toTimeline — purity + tolerance', () => {
  it('returns { entries: [] } for empty / non-array input', () => {
    expect(toTimeline([])).toEqual({ entries: [] })
    expect(toTimeline(null)).toEqual({ entries: [] })
    expect(toTimeline(undefined)).toEqual({ entries: [] })
  })

  it('does not mutate the input array', () => {
    const input = lifecycle()
    const before = JSON.stringify(input)
    toTimeline(input, { now: NOW })
    expect(JSON.stringify(input)).toBe(before)
  })

  it('is deterministic — identical input yields deeply-equal output', () => {
    const input = lifecycle()
    expect(toTimeline(input, { now: NOW })).toEqual(toTimeline(input, { now: NOW }))
  })

  it('tolerates malformed events without throwing', () => {
    const messy = [null, undefined, {}, { type: 'transcript_line' }, { type: 'phase_change', data: {} }]
    expect(() => toTimeline(messy, { now: NOW })).not.toThrow()
    // The lone phase_change (no phase) still opens a container; label degrades.
    const { entries } = toTimeline(messy, { now: NOW })
    expect(entries).toHaveLength(1)
  })
})
