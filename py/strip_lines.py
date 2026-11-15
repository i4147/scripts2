#!/usr/bin/env python3
"""
strip_lines.py - Remove specific blockquote lines from .md files (non-recursive).

Detected line prefixes to remove:
  > **Difficulty
  > **Prior
  > **Pivot

Usage:
  python strip_lines.py               # default: dry-run, shows a summary
  python strip_lines.py --dry-run     # show what would change (no writes)
  python strip_lines.py --diff        # show unified diffs of proposed changes
  python strip_lines.py --apply       # actually rewrite files in place

Flags are mutually exclusive; if none is given, --dry-run is assumed.
"""

import argparse
import difflib
import sys
from pathlib import Path

PREFIXES = (
    "> **Difficulty",
    "> **Prior",
    "> **Pivot required",
)


def line_matches(line: str) -> bool:
    """Return True if the line should be deleted."""
    return any(line.startswith(p) for p in PREFIXES)


def process_file(path: Path):
    """Return (original_text, new_text, removed_count)."""
    original = path.read_text(encoding="utf-8")
    # splitlines(keepends=True) preserves newlines so we can rebuild faithfully
    lines = original.splitlines(keepends=True)
    kept = [ln for ln in lines if not line_matches(ln)]
    removed = len(lines) - len(kept)
    return original, "".join(kept), removed


def main():
    parser = argparse.ArgumentParser(
        description="Remove specific blockquote lines from .md files in the current directory."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true",
                       help="Show what would change without writing (default).")
    group.add_argument("--diff", action="store_true",
                       help="Show unified diffs of proposed changes.")
    group.add_argument("--apply", action="store_true",
                       help="Rewrite files in place.")
    args = parser.parse_args()

    mode = "apply" if args.apply else "diff" if args.diff else "dry-run"

    cwd = Path.cwd()
    md_files = sorted(p for p in cwd.glob("*.md") if p.is_file())

    if not md_files:
        print(f"No .md files found in {cwd}")
        return 0

    total_changed = 0
    total_removed = 0

    for path in md_files:
        try:
            original, new_text, removed = process_file(path)
        except (OSError, UnicodeDecodeError) as e:
            print(f"[skip] {path.name}: {e}", file=sys.stderr)
            continue

        if removed == 0:
            continue

        total_changed += 1
        total_removed += removed

        if mode == "dry-run":
            print(f"[dry-run] {path.name}: would remove {removed} line(s)")
        elif mode == "diff":
            diff = difflib.unified_diff(
                original.splitlines(keepends=True),
                new_text.splitlines(keepends=True),
                fromfile=f"a/{path.name}",
                tofile=f"b/{path.name}",
            )
            sys.stdout.writelines(diff)
        elif mode == "apply":
            path.write_text(new_text, encoding="utf-8")
            print(f"[apply] {path.name}: removed {removed} line(s)")

    # Summary
    if mode == "dry-run":
        print(f"\nWould modify {total_changed} file(s), removing {total_removed} line(s).")
        print("Run with --diff to preview, or --apply to write changes.")
    elif mode == "apply":
        print(f"\nModified {total_changed} file(s), removed {total_removed} line(s).")
    else:  # diff
        print(f"\n{total_changed} file(s) would change ({total_removed} line(s) removed).")
        print("Run with --apply to write changes.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
