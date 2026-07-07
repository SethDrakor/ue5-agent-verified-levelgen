"""Pytest bootstrap for the python_toolchain test suite.

The toolchain is written against the UE5 Editor's embedded `unreal` module,
which only exists inside a running UE5 Editor process. There is no headless
substitute for the full API, and standing up a real editor in CI is out of
scope (see docs/CI.md for why).

What CAN be verified without an editor: that every file in python_toolchain
is syntactically valid and importable, and that the pieces of logic that
don't actually touch the engine (pure math, e.g. OccupancyGrid) behave
correctly. Both only require `unreal` to exist as a module — not to do
anything real. A MagicMock satisfies that: any attribute access or call on
it returns another MagicMock, which is enough for module-level statements
like `bgh = unreal.BlueprintGraphHelper` to succeed at import time.

This is intentionally NOT a simulation of the UE5 API. A test that needs
`unreal.something()` to return a specific, meaningful value belongs in the
in-editor suite (Content/Python/test_suite.py, 45 tests, run inside the
actual editor) — not here.
"""
import pathlib
import sys
from unittest.mock import MagicMock

TOOLCHAIN_DIR = pathlib.Path(__file__).resolve().parent.parent / "python_toolchain"
sys.path.insert(0, str(TOOLCHAIN_DIR))

if "unreal" not in sys.modules:
    sys.modules["unreal"] = MagicMock(name="unreal_stub")
