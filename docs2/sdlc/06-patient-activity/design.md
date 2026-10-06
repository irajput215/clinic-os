# Patient activity: design

## Screens

### Patient record → Activity

"Audit trail" card noting "Append-only, hash-chained", then a table.

## States

Skeleton, empty, `403` explanation, retry.

## Data flow

`resourceAuditQuery(patientId)` through the generated `AuditService.listAuditEvents`.

Tokens and components: [design-system.md](../../design-system.md).
