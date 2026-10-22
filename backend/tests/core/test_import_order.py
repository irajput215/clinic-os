"""Every module can be imported first, in a fresh interpreter, as a script would import it.

`scripts/prestart.sh` runs `app/initial_data.py` on every deploy, and that imports only what it needs,
long before the rest of the models are registered. A module that configures SQLAlchemy's mappers at
import time (reading a model's attributes through `sqlalchemy.inspect`, for one) fails there with
"failed to locate a name", though the app and the test suite, which import every model first, never
see it. A deploy would.
"""

import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "module",
    ["app.modules.audit.service", "app.core.db", "app.initial_data"],
)
def test_a_module_imports_first_in_a_fresh_interpreter(module: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
