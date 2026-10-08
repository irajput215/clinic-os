"""The Today page's aggregated read (`docs2/sdlc/08-today`).

The module owns no table. It composes the read facades of the modules that do own the data
(`appointments`, `prescriptions`, `tga_approvals`) on one tenant transaction, and is reached only
through [`service`](service.py).
"""
