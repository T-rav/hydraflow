import { useCallback } from 'react'

// Append the row's repo slug so a mutation in aggregate ("All repos") mode
// targets the issue's own repo, not the default one (ADR-0007 multi-repo).
const withRepo = (path, repo) =>
  repo ? `${path}?repo=${encodeURIComponent(repo)}` : path

export function useHITLCorrection() {
  const submitCorrection = useCallback(async (issueNumber, correction, repo) => {
    const resp = await fetch(withRepo(`/api/hitl/${issueNumber}/correct`, repo), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ correction }),
    })
    return resp.ok
  }, [])

  const skipIssue = useCallback(async (issueNumber, reason, repo) => {
    const resp = await fetch(withRepo(`/api/hitl/${issueNumber}/skip`, repo), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: reason || 'Skipped by operator' }),
    })
    return resp.ok
  }, [])

  const closeIssue = useCallback(async (issueNumber, reason, repo) => {
    const resp = await fetch(withRepo(`/api/hitl/${issueNumber}/close`, repo), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: reason || 'Closed by operator' }),
    })
    return resp.ok
  }, [])

  const approveProcess = useCallback(async (issueNumber, repo) => {
    const resp = await fetch(
      withRepo(`/api/hitl/${issueNumber}/approve-process`, repo),
      {
        method: 'POST',
      },
    )
    return resp.ok
  }, [])

  return { submitCorrection, skipIssue, closeIssue, approveProcess }
}
