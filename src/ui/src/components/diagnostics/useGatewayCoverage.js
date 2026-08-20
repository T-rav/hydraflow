import { useEffect, useState } from 'react'
import { EMPTY_GATEWAY_COVERAGE, toGatewayCoverage } from './gatewayCoverageModel'

export const GATEWAY_COVERAGE_POLL_MS = 60_000
export const GATEWAY_COVERAGE_ENDPOINT = '/api/diagnostics/gateway-coverage'

async function defaultFetcher(url, { signal } = {}) {
  const response = await fetch(url, { signal })
  if (!response.ok) throw new Error(`gateway coverage fetch failed: ${response.status}`)
  return response.json()
}

export function useGatewayCoverage({
  range = '24h',
  fetcher = defaultFetcher,
  scopeKey = '',
  intervalMs = GATEWAY_COVERAGE_POLL_MS,
} = {}) {
  const [coverage, setCoverage] = useState(EMPTY_GATEWAY_COVERAGE)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (typeof fetcher !== 'function') {
      setLoading(false)
      return undefined
    }

    const controller = new AbortController()
    const { signal } = controller
    const endpoint = `${GATEWAY_COVERAGE_ENDPOINT}?range=${encodeURIComponent(range)}`
    setCoverage(EMPTY_GATEWAY_COVERAGE)
    setLoading(true)
    setError(null)

    const load = async () => {
      try {
        const raw = await fetcher(endpoint, { signal })
        if (signal.aborted) return
        setCoverage(toGatewayCoverage(raw))
        setError(null)
      } catch (nextError) {
        if (!signal.aborted) setError(nextError)
      } finally {
        if (!signal.aborted) setLoading(false)
      }
    }

    load()
    const timer = setInterval(load, intervalMs)
    return () => {
      controller.abort()
      clearInterval(timer)
    }
  }, [fetcher, intervalMs, range, scopeKey])

  return { coverage, loading, error }
}

export default useGatewayCoverage
