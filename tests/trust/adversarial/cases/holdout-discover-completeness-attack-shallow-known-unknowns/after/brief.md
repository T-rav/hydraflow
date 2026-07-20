# Discovery Brief: Audit-log CSV export

## Intent

Give operators a one-click CSV download of the audit log so archival and
offline spreadsheet analysis stop requiring a database access request.

## Affected area

- `src/routes_audit.py` — new `/api/audit/export` endpoint
- `src/audit_store.py` — streaming row iterator for large logs
- `src/ui/views/AuditPanel.tsx` — download button and progress state

## Acceptance criteria

- `GET /api/audit/export` returns `text/csv` with a header row and HTTP 200
- A 100,000-row log streams to a complete file in under 30 seconds
- The exported row count equals the row count shown in the dashboard filter

## Open questions

- Should the export honor the currently-applied dashboard filters or always dump the full log?
- Do we cap the export size, and if so at how many rows?
- Is a UTC timestamp column enough, or do operators need local-time rendering?

## Known unknowns

None.
