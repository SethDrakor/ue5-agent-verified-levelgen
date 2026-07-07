# CI — what's actually checked, and what isn't

This repo has no access to a UE5 Editor, so CI cannot run the real
verification workflow that matters most for this project — the in-editor
`test_suite.py` (45 tests against the live plugin) and `verify_level.py`
(collision/NavMesh/gameplay checks against a live level). Standing up a
licensed Unreal Engine install in a public GitHub Actions runner isn't
practical (size, licensing, minutes) and would be theater more than signal:
a green check that doesn't actually exercise the editor is worse than no
check, because it invites false confidence.

So CI here is scoped to what's genuinely verifiable without an editor, and
it earned its place by catching two real bugs while it was being built —
not hypothetical ones.

## What it checks

**`scripts/check_repo_integrity.py`** (stdlib only, no dependencies).
No NUL bytes in any tracked Python/C++/JSON source file, every
`python_toolchain/*.py` file parses as valid Python, `RoomGenerator.uplugin`
is valid JSON, and every `.cpp`/`.h`/`*.Build.cs` file has balanced braces
after stripping comments and string literals. This is a "does it actually
parse" pass, not a compiler — see below for why that's still worth having.

**`scripts/check_doc_references.py`** (stdlib only). Every backtick-quoted
file reference and every markdown image link in `README.md` and `docs/*.md`
has to resolve to a real file in the repo. This repo's own git history has
two commits fixing exactly this class of drift.

**`tests/` via pytest.** `test_import_smoke.py` imports all four
`python_toolchain` modules under a mocked `unreal` module (a `MagicMock`
installed as `sys.modules["unreal"]` — good enough because the toolchain
only touches `unreal.*` at call time, never subclasses it at import time).
`test_occupancy_grid.py` unit-tests `OccupancyGrid`'s grid math for real
— it's pure logic with a single incidental `unreal.log()` call, so it's one
of the few pieces of this codebase whose actual *behavior* (not just
syntax) can be checked outside the editor.

**`ruff.toml`** restricts linting to pyflakes rules (`F`) — undefined
names, unused imports/variables, duplicate definitions. Full pycodestyle
style enforcement (`E`/`W`) is deliberately left off: the toolchain wasn't
written against a linter, and retrofitting house style onto ~5,000 lines of
working editor-automation code is a separate, purely cosmetic exercise with
real risk of burying real diffs in whitespace noise. This gate is about
catching real bugs, not about a particular formatting taste.

## What it deliberately does not check

No C++ compilation. No Blueprint compilation. No PIE run. No screenshot
comparison. No NavMesh build. Those all require a licensed Unreal Engine
install, which this CI does not and — realistically, given free-tier GitHub
Actions minutes and Epic's engine distribution terms — should not attempt.
The in-editor `test_suite.py` (45 tests, run manually before/after any
plugin change, see `docs/ARCHITECTURE.md`) remains the real safety net for
anything that touches the C++ subsystems or Blueprint graphs. CI here is a
second, narrower net underneath it — for the class of bug that doesn't need
an editor to catch, and that nothing was catching before.

## Running these checks before you even commit

Both bugs below were caught by CI — which means they were already pushed
to `master` by the time anything noticed. `scripts/hooks/pre-commit` runs
the same two structural checks (`check_repo_integrity.py`,
`check_doc_references.py`) as a git pre-commit hook, so a corrupted file
gets caught locally, before it's committed at all — not just before it's
merged.

One-time setup after cloning:

```
git config core.hooksPath scripts/hooks
```

After that, `git commit` runs the checks automatically and refuses to
commit if either one fails (`git commit --no-verify` bypasses it, and
shouldn't be needed — if you're reaching for it, fix the file instead).

## Why this exists: two bugs found while building it

**A silently truncated toolchain sync.** While writing the import-smoke
test, three of the four files in `python_toolchain/` (`ue5_utils.py`,
`verify_level.py`, `test_suite.py`) turned out to be truncated mid-function
— exact prefixes of the real files, cut off mid-statement, sitting on
`master` as valid-looking `.py` files that would `SyntaxError` on the first
real import. Nothing in this repo imported these files outside the UE5
editor before this CI existed, so nothing noticed. Fixed by re-syncing the
full files from the source project; `test_import_smoke.py` and
`check_repo_integrity.py` both now catch a recurrence of this specific
failure mode in seconds.

**A same-day, unrelated file-corruption bug in the editing environment
itself.** Two of those same files picked up several dozen trailing NUL
bytes purely from being edited (not from any sync step) — a shrink-in-place
edit that didn't fully truncate the old, longer file on disk. Caught by
`check_repo_integrity.py`'s NUL-byte scan before it was ever committed.
It's the same underlying risk as the sync truncation — "a file that looks
complete but isn't" — from a completely different cause, which is why the
check is a byte-level scan rather than something narrower tied to the sync
step alone.
