/**
 * Workflow-config view-model adapter for the operator console (#10786).
 *
 * Pure, deterministic transform of the settings-schema rows returned by
 * `GET /api/control/settings-schema` (each row carries a server-derived
 * `section` — see `settings_registry.section_for_group`) into an ORDERED list
 * of non-empty sections for the WorkflowConfigPanel to render.
 *
 * Design contract:
 *   - Total by construction: every input row lands in exactly one section, so
 *     no field is ever silently dropped from the panel. A row with a missing or
 *     unknown `section` falls into `Other` rather than vanishing.
 *   - Deterministic ordering: sections render in the declared `SECTION_ORDER`;
 *     any section the backend emits that is not in that list is appended (in
 *     first-appearance order) before `Other`, which is always rendered last.
 *   - Within a section, row order is preserved exactly as received (the backend
 *     already sorts rows by group/order/name).
 *   - No React, no side effects: same input → same output, input never mutated.
 *
 * Output shape:
 *   toWorkflowConfig(rows) -> [{ section: string, rows: Array<row> }, ...]
 */

// Must mirror the section names produced by `settings_registry.GROUP_TO_SECTION`
// on the backend. `Other` is the fallback bucket and is always rendered last.
export const OTHER_SECTION = 'Other'

export const SECTION_ORDER = Object.freeze([
  'Work Queue',
  'Workers & Batch',
  'Scheduling',
  'Model Routing',
  'CI & Quality',
  'Merge & Release',
  'Safety & Reliability',
  'Paths',
  OTHER_SECTION,
])

/** Resolve a row's section, coercing missing/blank/non-string to `Other`. */
function sectionOf(row) {
  const s = row && row.section
  return typeof s === 'string' && s.trim() ? s : OTHER_SECTION
}

/**
 * Bucket settings-schema rows into ordered, non-empty sections.
 * @param {Array<object>|null|undefined} rows - schema rows from the API.
 * @returns {Array<{ section: string, rows: Array<object> }>}
 */
export function toWorkflowConfig(rows) {
  const list = Array.isArray(rows) ? rows : []

  const buckets = new Map()
  const appearance = []
  for (const row of list) {
    if (!row || typeof row !== 'object') continue
    const section = sectionOf(row)
    if (!buckets.has(section)) {
      buckets.set(section, [])
      appearance.push(section)
    }
    buckets.get(section).push(row)
  }

  const ordered = []
  const seen = new Set()
  // Known sections first, in their declared display order (excluding Other).
  for (const name of SECTION_ORDER) {
    if (name === OTHER_SECTION) continue
    if (buckets.has(name)) {
      ordered.push(name)
      seen.add(name)
    }
  }
  // Any section the backend emitted that we don't know about — keep it visible
  // (totality) in first-appearance order, still before Other.
  for (const name of appearance) {
    if (name !== OTHER_SECTION && !seen.has(name)) {
      ordered.push(name)
      seen.add(name)
    }
  }
  // Other is always last so the catch-all never buries a named section.
  if (buckets.has(OTHER_SECTION)) ordered.push(OTHER_SECTION)

  return ordered.map((section) => ({ section, rows: buckets.get(section) }))
}

export default toWorkflowConfig
