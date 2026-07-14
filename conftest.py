"""
Shared pytest configuration for the dormancy test suite.

The `dormancy` package lives at `python/dormancy`, one level above this
`tests/` directory. Depending on how pytest is invoked (e.g. `pytest
python/tests` from the repo root vs. `cd python && pytest`), the `python/`
directory is not always automatically placed on `sys.path`. This conftest
guarantees `import dormancy` works regardless of invocation style, without
requiring a package install step.
"""
import os
import sys

_PYTHON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PYTHON_DIR not in sys.path:
    sys.path.insert(0, _PYTHON_DIR)
