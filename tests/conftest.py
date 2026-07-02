"""
Root conftest for hedge-quant tests.

eventkit (a dependency of ib_insync) calls asyncio.get_event_loop() at
module-import time.  On Python 3.14+ that raises RuntimeError when no loop is
set.  We seed a loop in pytest_configure (the earliest hook, before
collection) and eagerly import ib_insync right then so Python caches the
module.  All later lazy `import ib_insync` calls resolve from sys.modules
without hitting eventkit's initialisation code again.
"""
from __future__ import annotations

import asyncio
import contextlib


def pytest_configure(config: object) -> None:
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    # Eagerly initialise ib_insync while the loop is available so that
    # subsequent lazy imports (inside src/) hit the module cache, not
    # eventkit's loop-requiring __init__ code.
    with contextlib.suppress(Exception):
        import ib_insync  # noqa: F401