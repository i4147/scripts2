#!/data/data/com.termux/files/usr/bin/env python
"""
Reformat (reindent) Python files using black.

Usage examples:
  python reformat.py .                   # reformat all *.py under current dir
  python reformat.py src tools/x.py      # files and/or directories
  python reformat.py . --check           # report files that would change, exit 1 if any
  python reformat.py . --diff            # show unified diffs, don't write
  python reformat.py . --line-length 100
"""

import argparse
import difflib
import sys
from pathlib import Path

try:
    import black
except ImportError:
    sys.exit("black is not installed. Run: pip install black")


def collect_files(targets):
    files = set()
    for t in targets:
        p = Path(t)
        if p.is_dir():
            files.update(p.rglob("*.py"))
        elif p.suffix == ".py" and p.exists():
            files.add(p)
        else:
            print(f"skipping (not a .py file or directory): {t}", file=sys.stderr)
    return sorted(files)


def main():
    ap = argparse.ArgumentParser(description="Reformat Python files with black.")
    ap.add_argument("targets", nargs="+", help="files or directories")
    ap.add_argument("--check", action="store_true", help="don't write; exit 1 if any file would change")
    ap.add_argument("--diff", action="store_true", help="print unified diff; don't write")
    args = ap.parse_args()

    mode = black.Mode(line_length=120)
    files = collect_files(args.targets)
    changed, errors = 0, 0

    for f in files:
        src = f.read_text(encoding="utf-8")
        try:
            new = black.format_file_contents(src, fast=False, mode=mode)
        except black.NothingChanged:
            continue
        except black.InvalidInput as e:
            errors += 1
            print(f"ERROR (invalid Python, not changed): {f}: {e}", file=sys.stderr)
            continue

        changed += 1
        if args.diff:
            sys.stdout.writelines(
                difflib.unified_diff(
                    src.splitlines(keepends=True),
                    new.splitlines(keepends=True),
                    fromfile=f"{f} (before)",
                    tofile=f"{f} (after)",
                )
            )
        elif args.check:
            print(f"would reformat: {f}")
        else:
            f.write_text(new, encoding="utf-8")
            print(f"reformatted: {f}")

    print(f"\n{len(files)} checked, {changed} would change/changed, {errors} errors")
    if args.check and (changed or errors):
        sys.exit(1)
    if errors:
        sys.exit(2)


if __name__ == "__main__":
    main()
