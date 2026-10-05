"""Tenancy: tenant records and (later) tenant resolution.

Owned tables: `tenants`, and the tenancy half of session/token resolution
(`docs/reference/build-contract.md` §7). This package currently holds the table
model only; the endpoints arrive with the tenancy slice.
"""
