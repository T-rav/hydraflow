import { describe, it, expect } from 'vitest'
import { toTranscript } from '../transcript'

// Event shapes match the HydraFlowContext reducer:
//   transcript_line → data { source, issue, pr, line }
//   agent_activity  → data { source, issue, pr, activity_type, tool_name, summary, detail }

const line = (issue, text, extra = {}, id = 1) => ({
  type: 'transcript_line',
  timestamp: `2026-07-26T12:00:0${id}Z`,
  id,
  data: { issue, line: text, ...extra },
})

const activity = (issue, fields, id = 1) => ({
  type: 'agent_activity',
  timestamp: `2026-07-26T12:00:0${id}Z`,
  id,
  data: { issue, ...fields },
})

describe('toTranscript', () => {
  it('parses agent_activity into typed rows (read/edit/run) with meta', () => {
    const events = [
      activity(42, { source: 'implementer', activity_type: 'tool_call', tool_name: 'Read', summary: 'src/app.py' }, 1),
      activity(42, { source: 'implementer', activity_type: 'tool_call', tool_name: 'Edit', summary: 'src/app.py' }, 2),
      activity(42, { source: 'implementer', activity_type: 'tool_call', tool_name: 'Bash', summary: 'pytest -q' }, 3),
    ]
    const rows = toTranscript(events, 42)
    expect(rows.map(r => r.kind)).toEqual(['read', 'edit', 'run'])
    expect(rows[0]).toMatchObject({
      kind: 'read',
      text: 'src/app.py',
      meta: { source: 'implementer', tool: 'Read', activityType: 'tool_call', issue: 42 },
    })
    expect(rows[2].kind).toBe('run')
  })

  it('classifies transcript_line text into pass/fail/agent kinds', () => {
    const events = [
      line(42, '✓ 214 tests passed', {}, 1),
      line(42, 'FAILED tests/test_foo.py::test_bar', {}, 2),
      line(42, 'Thinking about the approach', {}, 3),
    ]
    const rows = toTranscript(events, 42)
    expect(rows.map(r => r.kind)).toEqual(['pass', 'fail', 'agent'])
  })

  it('orders rows chronologically (oldest first) regardless of input order', () => {
    // Reducer stores events newest-first; the transcript renders oldest-first.
    const events = [
      line(42, 'third', {}, 3),
      line(42, 'first', {}, 1),
      line(42, 'second', {}, 2),
    ]
    const rows = toTranscript(events, 42)
    expect(rows.map(r => r.text)).toEqual(['first', 'second', 'third'])
  })

  it('filters to the requested issueId only', () => {
    const events = [
      line(42, 'for 42', {}, 1),
      line(99, 'for 99', {}, 2),
    ]
    expect(toTranscript(events, 42).map(r => r.text)).toEqual(['for 42'])
  })

  it('attributes reviewer transcript lines keyed on the PR number', () => {
    const events = [
      { type: 'transcript_line', timestamp: '2026-07-26T12:00:01Z', id: 1, data: { source: 'reviewer', pr: 555, line: 'reviewing diff' } },
    ]
    expect(toTranscript(events, 555).map(r => r.text)).toEqual(['reviewing diff'])
  })

  // Regression: the known `transcript line#undefined` bug (EventLog.eventSummary
  // rendered `#${data.issue || data.pr}` = `#undefined` when both were absent).
  it('drops transcript lines with no issue/pr id — never emits an #undefined header', () => {
    const events = [
      line(42, 'legit line', {}, 1),
      { type: 'transcript_line', timestamp: '2026-07-26T12:00:02Z', id: 2, data: { line: 'orphan with no id' } },
    ]
    const rows = toTranscript(events, 42)
    expect(rows.map(r => r.text)).toEqual(['legit line'])
    // No row is attributed to an undefined item, and nothing leaks `#undefined`.
    for (const r of rows) {
      expect(r.meta.issue).not.toBeUndefined()
      expect(String(r.text)).not.toContain('#undefined')
      expect(JSON.stringify(r.meta)).not.toContain('undefined')
    }
  })

  it('repairs a line whose text carries a literal #undefined prefix', () => {
    const events = [line(42, '#undefined committing changes', {}, 1)]
    const rows = toTranscript(events, 42)
    expect(rows[0].text).toBe('committing changes')
    expect(rows[0].text).not.toContain('#undefined')
  })

  it('with no issueId, returns all attributable rows and still drops id-less ones', () => {
    const events = [
      line(42, 'a', {}, 1),
      line(99, 'b', {}, 2),
      { type: 'transcript_line', timestamp: '2026-07-26T12:00:03Z', id: 3, data: { line: 'orphan' } },
    ]
    const rows = toTranscript(events)
    expect(rows.map(r => r.text).sort()).toEqual(['a', 'b'])
  })

  it('is pure — identical input yields deeply-equal output', () => {
    const events = [
      activity(42, { source: 'implementer', activity_type: 'tool_call', tool_name: 'Read', summary: 'f' }, 1),
      line(42, 'ok', {}, 2),
    ]
    expect(toTranscript(events, 42)).toEqual(toTranscript(events, 42))
  })
})
