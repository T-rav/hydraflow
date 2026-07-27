/**
 * Settings-summary view-model adapter for the operator console (epic #10556
 * follow-up).
 *
 * Pure, deterministic transform of the `/api/control/status` `config` object
 * (already in the frontend as the HydraFlow context `config` slice, populated
 * by the `CONFIG` action) into a small "at-a-glance" view model of the KEY
 * runtime settings shown inline under the Loops panel.
 *
 * The full System-tab configuration is reachable via the gear affordance
 * (SettingsSummary -> SettingsDrawer -> the classic SystemPanel); this adapter
 * only surfaces the handful of settings an operator most wants to eyeball
 * without opening the drawer.
 *
 * Field names mirror the backend `ControlStatusConfig` model
 * (src/dashboard_routes/_control_routes.py `_control_status_config`):
 *   model, max_workers, max_planners, max_reviewers, batch_size,
 *   queue_strategy (a StrEnum serialized to e.g. "weighted_mix"),
 *   merge_policy_enabled.
 *
 * Output shape:
 *   toSettingsSummary(config) -> {
 *     items: [{ key, label, value }],   // display-ready chips/rows
 *     model, maxWorkers, maxPlanners, maxReviewers, batchSize,
 *     queueStrategy, mergePolicy,       // raw values (or null when absent)
 *   }
 *
 * No React, no side effects: given the same input it returns the same output,
 * and it never mutates the input config.
 */

// Shown for a missing / null / empty setting so a chip never renders blank.
const PLACEHOLDER = '—'

/** Coerce a raw setting into a display string; null/undefined/'' -> placeholder. */
function displayValue(v) {
  if (v == null || v === '') return PLACEHOLDER
  return String(v)
}

/**
 * Build the at-a-glance settings view model.
 * @param {object|null|undefined} config - the context `config` slice.
 * @returns {{
 *   items: Array<{ key: string, label: string, value: string }>,
 *   model: string|null,
 *   maxWorkers: number|null,
 *   maxPlanners: number|null,
 *   maxReviewers: number|null,
 *   batchSize: number|null,
 *   queueStrategy: string|null,
 *   mergePolicy: boolean|null,
 * }}
 */
export function toSettingsSummary(config) {
  const c = config && typeof config === 'object' ? config : {}

  const model = c.model ?? null
  const maxWorkers = c.max_workers ?? null
  const maxPlanners = c.max_planners ?? null
  const maxReviewers = c.max_reviewers ?? null
  const batchSize = c.batch_size ?? null
  const queueStrategy = c.queue_strategy ?? null
  // merge_policy_enabled is a boolean toggle; keep only an explicit boolean,
  // everything else (missing / non-bool) reads as "unknown" (null).
  const mergePolicy = typeof c.merge_policy_enabled === 'boolean' ? c.merge_policy_enabled : null

  const items = [
    { key: 'model', label: 'Model', value: displayValue(model) },
    { key: 'workers', label: 'Workers', value: displayValue(maxWorkers) },
    { key: 'planners', label: 'Planners', value: displayValue(maxPlanners) },
    { key: 'reviewers', label: 'Reviewers', value: displayValue(maxReviewers) },
    { key: 'batch', label: 'Batch', value: displayValue(batchSize) },
    { key: 'queue', label: 'Queue', value: displayValue(queueStrategy) },
    {
      key: 'merge',
      label: 'Merge policy',
      value: mergePolicy == null ? PLACEHOLDER : (mergePolicy ? 'on' : 'off'),
    },
  ]

  return {
    items,
    model,
    maxWorkers,
    maxPlanners,
    maxReviewers,
    batchSize,
    queueStrategy,
    mergePolicy,
  }
}

export default toSettingsSummary
