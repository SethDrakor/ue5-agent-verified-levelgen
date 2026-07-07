"""Import-smoke tests for python_toolchain.

This is a deliberately low bar: does each file parse and execute its
module-level code under the `unreal` stub? It does not check that any
UE5-dependent behavior is correct — it can't, outside an editor.

That low bar still has teeth. A previous sync of this repo (see git history
around "Sync toolchain") shipped three of these files truncated mid-function
— valid enough to sit in the repo and look complete, but a SyntaxError the
instant anything tried to import them. Nothing in this repo caught that
before now, because nothing outside the UE5 editor ever imported these
files. This test exists so a truncated or otherwise broken file fails CI
within seconds instead of silently sitting on `master`.
"""
import importlib

import pytest

MODULES = ["ue5_utils", "verify_level", "horror_presets", "test_suite"]


@pytest.mark.parametrize("module_name", MODULES)
def test_module_imports_cleanly(module_name):
    importlib.import_module(module_name)
