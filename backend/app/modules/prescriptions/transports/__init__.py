"""Outbound prescription transports (FEAT-13 "Adapter contract", D-012).

* `resilience.ResilientTransport` wraps any `DispatchTransport` with the FEAT-13 controls: an overall
  deadline, bounded retries with full jitter for failures that provably never left, a circuit breaker
  and a bulkhead.
* `parchment.ParchmentTransport` is the Parchment eRx adapter. It speaks to Parchment through a narrow
  `ParchmentWire`; the only wire that exists is `SimulatedParchmentWire`, because Parchment's API
  documentation and sandbox are not yet available (D-012 open item 1). No real HTTP wire is
  written against a guessed API.

Nothing here is selected by `transport.configured_transport()`, which still returns `None`: no
prescription leaves ClinicOS until a real wire exists and D-012 §5 is satisfied.
"""
