#!/usr/bin/env python3
"""
Knowledge Scanner — 使用 find 加速 WSL 文件枚舉。

因為 WSL /mnt/c/ 的 stat() 極慢，先用 find 枚舉文件名稱和擴展名，
然後用 Python 做分類統計。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)

SEARCH_ROOTS = [
    "/mnt/c/users/bzhao/Documents/Study Materials",
    "/mnt/c/users/bzhao/Documents/SAP",
    "/mnt/c/users/bzhao/Documents/HANA",
    "/mnt/c/users/bzhao/Documents/Issue List",
]

DIRECT_EXTS = {'.pdf', '.docx', '.doc', '.pptx', '.ppt', '.xlsx', '.xls',
               '.html', '.htm', '.txt', '.md', '.csv', '.json', '.xml',
               '.png', '.jpg', '.jpeg', '.tiff', '.tif'}

SPECIAL_EXTS = {'.chm', '.mp4', '.mov', '.avi', '.vsdx', '.vsd', '.msg',
                '.eml', '.zip', '.7z', '.rar', '.ipynb', '.sqlite', '.db'}

SKIP_DIRS = {'__pycache__', '.git', '.svn', 'node_modules', 'venv', '.venv',
             '_images', '_static', 'images', 'img', 'temp', 'tmp', 'backup',
             'archive', 'bin', 'obj', 'lib', 'include', 'Common7', 'VC',
             'MSBuild', 'Microsoft', 'Windows', 'Bootcamp', 'Python', 'Ruby',
             'Go', 'Rust', '.arcgis', 'arcgis', 'ArcGIS'}

# Build find exclude for skip dirs
FIND_EXCLUDE = ' '.join(f'-path "*/{d}/*" -prune -o' for d in SKIP_DIRS)


def scan_root(root: str, max_depth: int = 6) -> Counter:
    """Use find to enumerate files, return extension counts."""
    find_cmd = (
        f'find "{root}" -maxdepth {max_depth} '
        f'-type f '
        f'! -name ".*" '
        f'2>/dev/null'
    )
    try:
        result = subprocess.run(
            find_cmd, shell=True, capture_output=True, text=True, timeout=30
        )
    except subprocess.TimeoutExpired:
        print(f"  [TIMEOUT] {root}")
        return Counter()

    files = result.stdout.strip().split("\n") if result.stdout.strip() else []
    ext_counter = Counter()
    for fpath in files:
        ext = Path(fpath).suffix.lower()
        ext_counter[ext] += 1

    return ext_counter


def main():
    parser = argparse.ArgumentParser(description="Knowledge Scanner (fast)")
    parser.add_argument("--output", type=str, default=None,
                        help="JSON report path")
    args = parser.parse_args()

    print(f"Knowledge Scanner (fast) — {datetime.now().isoformat()}")
    print(f"Roots: {len(SEARCH_ROOTS)}")
    print("=" * 50)

    all_exts = Counter()
    root_exts: dict[str, Counter] = {}

    for root in SEARCH_ROOTS:
        if not Path(root).exists():
            print(f"  [SKIP] {root} — not found")
            continue
        print(f"  Scanning: {root}...", end=" ", flush=True)
        ext_counts = scan_root(root)
        root_exts[root] = ext_counts
        all_exts += ext_counts
        print(f"{sum(ext_counts.values())} files, {len(ext_counts)} formats")

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"\n  Total files: {sum(all_exts.values())}")

    print(f"\n  Direct ingest (doc2md supports):")
    direct_total = 0
    for ext in sorted(DIRECT_EXTS):
        count = all_exts.get(ext, 0)
        if count > 0:
            print(f"    {ext:8s} {count:>6d}")
            direct_total += count

    print(f"\n  Needs special pipeline:")
    special_total = 0
    for ext in sorted(SPECIAL_EXTS):
        count = all_exts.get(ext, 0)
        if count > 0:
            print(f"    {ext:8s} {count:>6d}")
            special_total += count

    other_total = sum(all_exts.values()) - direct_total - special_total
    if other_total > 0:
        print(f"\n  Unknown formats (total): {other_total}")

    print(f"\n  Total ingestible (direct + special): {direct_total + special_total}")

    # Per-root breakdown for direct formats
    print(f"\n  Per-root breakdown (direct formats):")
    for root in SEARCH_ROOTS:
        if root not in root_exts:
            continue
        total = sum(root_exts[root].get(ext, 0) for ext in DIRECT_EXTS)
        if total > 0:
            print(f"    {Path(root).name:30s} {total:>6d} files")

    if args.output:
        report = {
            "scan_time": datetime.now().isoformat(),
            "roots": SEARCH_ROOTS,
            "total_files": sum(all_exts.values()),
            "direct_formats": {k: v for k, v in all_exts.items() if k in DIRECT_EXTS},
            "special_formats": {k: v for k, v in all_exts.items() if k in SPECIAL_EXTS},
        }
        with open(args.output, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\n  Report saved: {args.output}")

    print(f"\n  Done.")


if __name__ == "__main__":
    main()
