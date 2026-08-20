/** Pure view model for the gateway spend-coverage gauge. */

export const GATEWAY_COVERAGE_COMPLETE = 'complete'
export const GATEWAY_COVERAGE_PARTIAL = 'partial'
export const GATEWAY_COVERAGE_NO_DATA = 'no_data'

export const EMPTY_GATEWAY_COVERAGE = Object.freeze({
  status: GATEWAY_COVERAGE_NO_DATA,
  statusLabel: 'No spend data',
  tone: 'neutral',
  displayPercent: null,
  valueLabel: 'No spend',
  meterLabel: 'No LLM spend observed in this window',
  scopeLabel: 'Current repo',
  windowLabel: '24h',
  gatewaySpendUsd: 0,
  bypassSpendUsd: 0,
  knownTotalSpendUsd: 0,
  gatewayRequests: 0,
  bypassRequests: 0,
  unknownRequests: 0,
  sourceDataComplete: true,
  bypassingFamilies: Object.freeze([]),
  ceilingAchieved: false,
  regressionDetected: false,
})

function finiteNumber(value, fallback = 0) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

function percentOrNull(value) {
  if (value == null) return null
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return null
  return Math.max(0, Math.min(100, parsed))
}

function normalizeFamilies(value) {
  if (!Array.isArray(value)) return []
  return value
    .filter((row) => row && typeof row === 'object')
    .map((row) => ({
      family: String(row.family || 'unattributed'),
      calls: Math.max(0, finiteNumber(row.calls)),
      spendUsd: Math.max(0, finiteNumber(row.spend_usd)),
      unpricedCalls: Math.max(0, finiteNumber(row.unpriced_calls)),
      providers: Array.isArray(row.providers) ? row.providers.map(String) : [],
      repos: Array.isArray(row.repos) ? row.repos.map(String) : [],
    }))
}

function statusOf(raw) {
  if (raw.status === GATEWAY_COVERAGE_COMPLETE) return GATEWAY_COVERAGE_COMPLETE
  if (raw.status === GATEWAY_COVERAGE_PARTIAL) return GATEWAY_COVERAGE_PARTIAL
  return GATEWAY_COVERAGE_NO_DATA
}

export function toGatewayCoverage(raw) {
  if (!raw || typeof raw !== 'object') return EMPTY_GATEWAY_COVERAGE

  const status = statusOf(raw)
  const claimedPercent = percentOrNull(raw.coverage_percent)
  const knownPercent = percentOrNull(raw.known_spend_coverage_percent)
  const unknownRequests =
    Math.max(0, finiteNumber(raw.unpriced_gateway_requests))
    + Math.max(0, finiteNumber(raw.unpriced_bypass_requests))
  const partial = status === GATEWAY_COVERAGE_PARTIAL
  const sourceDataComplete = raw.source_data_complete !== false
  const partialPricing = partial && sourceDataComplete && unknownRequests > 0
  const displayPercent = status === GATEWAY_COVERAGE_COMPLETE
    ? claimedPercent
    : partialPricing
      ? knownPercent
      : null
  const roundedLabel = displayPercent == null ? null : `${displayPercent.toFixed(1)}%`
  const regressionDetected = raw.regression_detected === true

  return {
    status,
    statusLabel: regressionDetected
      ? 'Regression'
      : partialPricing
      ? 'Partial pricing'
      : partial
        ? 'Incomplete evidence'
      : status === GATEWAY_COVERAGE_COMPLETE
        ? 'Complete'
        : 'No spend data',
    tone: regressionDetected
      ? 'danger'
      : partial
      ? 'warning'
      : status === GATEWAY_COVERAGE_COMPLETE
        ? 'success'
        : 'neutral',
    displayPercent,
    valueLabel: roundedLabel == null
      ? partial ? 'Coverage unknown' : 'No spend'
      : partialPricing
        ? `${roundedLabel} known spend`
        : roundedLabel,
    meterLabel: roundedLabel == null
      ? partialPricing
        ? 'Partial pricing: spend observed but total coverage cannot be calculated'
        : partial
          ? 'Coverage evidence is incomplete; no total coverage claim is available'
        : 'No LLM spend observed in this window'
      : partialPricing
        ? `Partial pricing: ${roundedLabel} of known spend transited the gateway`
        : `${roundedLabel} of LLM spend transited the gateway`,
    scopeLabel: raw.scope === 'global'
      ? 'All repos'
      : String(raw.repo_slug || 'Current repo'),
    windowLabel: String(raw.window_label || '24h'),
    gatewaySpendUsd: Math.max(0, finiteNumber(raw.gateway_spend_usd)),
    bypassSpendUsd: Math.max(0, finiteNumber(raw.bypass_spend_usd)),
    knownTotalSpendUsd: Math.max(0, finiteNumber(raw.known_total_spend_usd)),
    gatewayRequests: Math.max(0, finiteNumber(raw.gateway_requests)),
    bypassRequests: Math.max(0, finiteNumber(raw.bypass_requests)),
    unknownRequests,
    sourceDataComplete,
    bypassingFamilies: normalizeFamilies(raw.bypassing_families),
    ceilingAchieved: raw.ceiling_achieved === true,
    regressionDetected,
  }
}
