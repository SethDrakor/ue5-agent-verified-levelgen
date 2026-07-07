#!/usr/bin/env python3
"""check_doc_references.py — flags stale file references in README/docs.

This repo's git history includes at least two commits fixing exactly this
("Fix corrupted Proof section in README", "...stale doc refs in
horror_presets.py") — a doc pointing at a file, path, or image that no
longer matches reality. That's an easy failure mode for a recruiting
showcase repo specifically: it's the kind of small inconsistency a
technical reviewer notices immediately, and it tends to happen exactly when
files get moved/renamed without a grep pass over the docs.

What this checks, in README.md and docs/*.md:
  - Markdown image links: ![...](path) — the path must exist.
  - Backtick-quoted filenames ending in a known source/doc extension
    (.py, .md, .png, .uplugin, .cs, .cpp, .h) — either at the given relative
    path, or matching exactly one file elsewhere in the repo by basename
    (covers references like `ue5_utils.py` used without the
    `python_toolchain/` prefix, common in prose).

Deliberately NOT checked: UE5 asset paths (`/Game/...`, `/Script/...`) —
those live inside the .uproject, not this repo, and aren't resolvable here.
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

DOC_FILES = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]

BACKTICK_PATH_RE = re.compile(
    r"`([A-Za-z0-9_./-]+\.(?:py|md|png|uplugin|cs|cpp|h))`"
)
IMAGE_LINK_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")


def _basename_index() -> dict[str, list[pathlib.Path]]:
    index: dict[str, list[pathlib.Path]] = {}
    for f in ROOT.rglob("*"):
        if ".git" in f.parts:
            continue
        if f.is_file():
            index.setdefault(f.name, []).append(f)
    return index


def check() -> list[str]:
    problems: list[str] = []
    basenames = _basename_index()

    for doc in DOC_FILES:
        text = doc.read_text(encoding="utf-8")

        for match in IMAGE_LINK_RE.finditer(text):
            ref = match.group(1)
            if ref.startswith(("http://", "https://")):
                continue
            if not (doc.parent / ref).exists() and not (ROOT / ref).exists():
                problems.append(f"{doc.relative_to(ROOT)}: broken image link '{ref}'")

        for match in BACKTICK_PATH_RE.finditer(text):
            ref = match.group(1)
            if (ROOT / ref).exists():
                continue
            candidates = basenames.get(pathlib.Path(ref).name, [])
            if len(candidates) == 0:
                problems.append(
                    f"{doc.relative_to(ROOT)}: reference `{ref}` does not "
                    "match any file in the repo"
                )
            # len == 1 (resolved elsewhere) or > 1 (ambiguous but at least
            # exists somewhere) — both treated as OK. Ambiguity across
            # several same-named files isn't this script's problem to
            # arbitrate.

    return problems


def main() -> int:
    problems = check()
    if problems:
        print(f"DOC REFERENCES: {len(problems)} problem(s) found\n")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("DOC REFERENCES: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
