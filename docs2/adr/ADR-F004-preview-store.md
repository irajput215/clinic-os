# ADR-F004: A labelled preview store for features without a backend

- **Status:** Accepted
- **Date:** 2026-10-06

## Context

The clinical flow needs appointments, prescriptions, a dashboard and public booking. None of those
has a backend module. Clinical records and TGA approvals are being built on other branches. The
brief was a functional app now, with a backend owner who decides the server contracts.

Options considered:

1. Wait for the backends. That blocks all UI work and gives the backend owners no tested UI contract.
2. Hard-coded mock JSON. It can't exercise refusals, links break, and mocks drift silently.
3. A mock HTTP layer (MSW). It's realistic, but it puts a fake API at the network boundary, where
   it can be mistaken for the real one.
4. **A repository layer with an `api` and a `preview` implementation behind one interface**, with
   the preview enforcing the documented server rules, clearly labelled on screen.

## Decision

Option 4. See [capabilities.md](../capabilities.md) for the mechanics.

## Consequences

- The screens are complete and tested end to end now, including every refusal path.
- Switching a feature to the API is a one-line change in `capabilities.ts`. For the two in-flight
  modules, the API adapters are already written against their real routes.
- The preview's rules are a second copy of server rules. They are kept honest by being MIRROR-typed,
  commented with the backend file they copy, and retired feature by feature as backends merge.
  The preview is never a security control.
- Users see a **Preview data** banner on every affected screen until the switch.
