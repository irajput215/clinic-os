"""Users and roles: the tenant-scoped role bundles and the central policy layer.

Owns the `roles`, `permissions`, `role_permissions` and `user_roles` tables
([`build-contract.md` §7](../../../../docs/reference/build-contract.md), module `users_roles`) and
exposes `can(actor, permission, resource)` as the single place an authorisation decision is made
(`docs/features/03-users-and-roles/03-design.md`, "The central policy layer").

The real `users` table is task T1-03 and is blocked by **D-003**; until it lands, `user_roles`
references the legacy `user` table. That deviation is recorded in the migration docstring.
"""
