#!/usr/bin/env python3
"""check_repo_integrity.py — structural integrity guard for this repo.

Twice in this project's history a file has looked complete — right
extension, plausible size, sitting quietly in the repo — while actually
being corrupted: a bad toolchain sync once silently truncated three Python
files mid-statement (found while wiring up this CI), and a routine text
edit on the working filesystem separately left ~80 trailing NUL bytes on
two files with no error raised (found while testing this very check).
Both failures share a signature: the file looks fine until something
actually parses it, and nothing in this repo did that automatically before.

This script is the "does it actually parse" pass. It runs on every push
with zero external dependencies (stdlib only):

  1. No NUL bytes anywhere in the tracked source files below.
  2. Every python_toolchain/*.py file parses as valid Python (ast.parse).
  3. RoomGenerator.uplugin is valid JSON.
  4. Every Plugin/**/*.cpp, *.h and Build.cs has balanced braces after
     stripping comments and string/char literals — a cheap proxy for "not
     truncated mid-function". A full UE5 compile isn't feasible in CI
     (no engine, no license to redistribute one) — see docs/CI.md for why
     that's a deliberate scope decision, not an oversight.

This is NOT a substitute for actually compiling the plugin or running the
in-editor 45-test anti-regression suite — it catches "obviously broken",
not "wrong". It exists because "obviously broken" already happened twice
and nothing caught it.
"""
from __future__ import annotations

import ast
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

NULL_BYTE_GLOBS = [
    "python_toolchain/*.py",
    "Plugin/RoomGenerator/Source/**/*.cpp",
    "Plugin/RoomGenerator/Source/**/*.h",
    "Plugin/RoomGenerator/Source/**/*.Build.cs",
    "Plugin/RoomGenerator/*.uplugin",
]

BRACE_GLOBS = [
    "Plugin/RoomGenerator/Source/**/*.cpp",
    "Plugin/RoomGenerator/Source/**/*.h",
    "Plugin/RoomGenerator/Source/**/*.Build.cs",
]

problems: list[str] = []


def _files(pattern: str) -> list[pathlib.Path]:
    return sorted(ROOT.glob(pattern))


def check_no_null_bytes() -> None:
    for pattern in NULL_BYTE_GLOBS:
        for f in _files(pattern):
            data = f.read_bytes()
            if b"\x00" in data:
                count = data.count(b"\x00")
                problems.append(
                    f"{f.relative_to(ROOT)}: contains {count} NUL byte(s) "
                    "— file is likely truncated or corrupted"
                )


def check_python_parses() -> None:
    for f in _files("python_toolchain/*.py"):
        try:
            ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        except (SyntaxError, ValueError) as e:
            # ValueError covers "source code string cannot contain null
            # bytes" — ast.parse doesn't raise SyntaxError for that case,
            # even though it's exactly the kind of corruption this check
            # exists to catch.
            problems.append(f"{f.relative_to(ROOT)}: does not parse: {e}")


def check_uplugin_json() -> None:
    for f in _files("Plugin/RoomGenerator/*.uplugin"):
        try:
            json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            problems.append(f"{f.relative_to(ROOT)}: invalid JSON: {e}")


# Strips // line comments, /* */ block comments, and string/char literals so
# brace-counting isn't thrown off by a stray '{' inside a log message.
# Deliberately not a real C++ tokenizer — good enough for this repo's style.
_STRING_OR_COMMENT = re.compile(
    r"//.*?$"
    r"|/\*.*?\*/"
    r"|\"(?:\\.|[^\"\\])*\""
    r"|'(?:\\.|[^'\\])*'",
    re.DOTALL | re.MULTILINE,
)


def _strip_strings_and_comments(text: str) -> str:
    return _STRING_OR_COMMENT.sub("", text)


def check_brace_balance() -> None:
    for pattern in BRACE_GLOBS:
        for f in _files(pattern):
            text = _strip_strings_and_comments(
                f.read_text(encoding="utf-8", errors="replace")
            )
            depth = 0
            unexpected_close = False
            for ch in text:
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth < 0:
                        unexpected_close = True
                        break
            if unexpected_close:
                problems.append(
                    f"{f.relative_to(ROOT)}: unbalanced braces (unexpected '}}')"
                )
            elif depth != 0:
                problems.append(
                    f"{f.relative_to(ROOT)}: unbalanced braces "
                    f"({depth} unclosed '{{' — file may be truncated)"
                )


def main() -> int:
    check_no_null_bytes()
    check_python_parses()
    check_uplugin_json()
    check_brace_balance()

    if problems:
        print(f"REPO INTEGRITY: {len(problems)} problem(s) found\n")
        for p in problems:
            print(f"  - {p}")
        return 1

    print("REPO INTEGRITY: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
