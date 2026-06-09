/**
 * Split an Atlas graph node id into its owning repo slug and bare id.
 *
 * Under `repo=__all__` the backend namespaces every node id with `${slug}/`
 * (so terms/ADRs/entries sharing an id across repos don't collide). A
 * single-repo graph keeps un-prefixed ids. This recovers the slug + bare id so
 * a detail fetch can scope to the right repo:
 *   "org-a/01TERM…"  → { repo: "org-a", bareId: "01TERM…" }
 *   "org-a/adr-59"   → { repo: "org-a", bareId: "adr-59" }
 *   "01TERM…"        → { repo: null,    bareId: "01TERM…" }
 *
 * Bare ids never contain `/` (slugs do not either — they are dash-normalized),
 * so the first `/` is unambiguously the namespace separator.
 */
export function splitNodeId(nodeId) {
  if (!nodeId || typeof nodeId !== 'string') return { repo: null, bareId: nodeId }
  const i = nodeId.indexOf('/')
  if (i > 0) return { repo: nodeId.slice(0, i), bareId: nodeId.slice(i + 1) }
  return { repo: null, bareId: nodeId }
}
