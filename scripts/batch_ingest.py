#!/usr/bin/env python3
"""
Batch Ingest — 全格式批量攝入 KAFED。

高效策略：
  1. CHM → 7z extract → markitdown batch (一次 Python 進程處理全部)
  2. HTML/HTM → markitdown 批量 (每目錄一次 Python 進程)
  3. PDF/DOCX/PPTX/XLSX → doc2md (已有高效工具)
  4. 圖片 → OCR (需要時啟用)

用法:
  cd ~/KAFED && source .venv/bin/activate
  python3 scripts/batch_ingest.py [--dry-run] [--limit N] [--skip-chm] [--skip-html]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)

KAFED_ROOT = Path.home() / "KAFED"
DOC2MD = Path.home() / "bin" / "doc2md"
MARKITDOWN_VENV = Path.home() / ".local" / "venvs" / "markitdown"

# 搜索根
SEARCH_ROOTS = [
    Path("/mnt/c/users/bzhao/Documents/Study Materials"),
    Path("/mnt/c/users/bzhao/Documents/SAP"),
    Path("/mnt/c/users/bzhao/Documents/HANA"),
]

# 每次 markitdown 調用處理的文件數（減輕 Python 啟動開銷）
BATCH_SIZE = 50

# 已攝入追蹤
INGESTED_LOG = KAFED_ROOT / "data" / "ingested_files.json"


def load_ingested() -> set[str]:
    if INGESTED_LOG.exists():
        try:
            with open(INGESTED_LOG) as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()


def save_ingested(paths: set[str]) -> None:
    INGESTED_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(INGESTED_LOG, "w") as f:
        json.dump(sorted(paths), f, indent=2)


def convert_with_markitdown(files: list[Path], output_dir: Path) -> int:
    """Batch convert files using a single markitdown Python call."""
    if not files:
        return 0

    # Build Python script that processes all files
    py_script = f"""import sys, json
sys.path.insert(0, '{MARKITDOWN_VENV / "lib" / "python3.14" / "site-packages"}')
from markitdown import MarkItDown
md = MarkItDown()
files = {json.dumps([str(f) for f in files])}
results = []
for fpath in files:
    try:
        result = md.convert(fpath)
        content = result.text_content[:100000]  # cap at 100K chars
        results.append({{"path": fpath, "ok": True, "len": len(content), "content": content}})
    except Exception as e:
        results.append({{"path": fpath, "ok": False, "error": str(e)[:200]}})
print(json.dumps(results))
"""
    try:
        result = subprocess.run(
            [sys.executable, "-c", py_script],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            print(f"  [FAIL] batch markitdown: {result.stderr[:200]}")
            return 0

        data = json.loads(result.stdout)
        ok_count = 0
        for item in data:
            fpath = Path(item["path"])
            if item["ok"] and item["content"].strip():
                # Write to markdown file
                md_path = output_dir / f"{fpath.stem}.md"
                with open(md_path, "w") as f:
                    f.write(item["content"])
                ok_count += 1
        return ok_count
    except Exception as e:
        print(f"  [FAIL] batch: {e}")
        return 0


def convert_chm(chm_path: Path, output_dir: Path) -> int:
    """Convert a single CHM file to markdown."""
    result = subprocess.run(
        [str(DOC2MD), "--chm", "--clean", str(chm_path)],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        return 0
    content = result.stdout.strip()
    if not content:
        return 0

    # Save to file
    md_path = output_dir / f"{chm_path.stem}.md"
    with open(md_path, "w") as f:
        f.write(content)
    return 1


def main():
    parser = argparse.ArgumentParser(description="Batch Ingest")
    parser.add_argument("--dry-run", action="store_true", help="審核不改")
    parser.add_argument("--limit", type=int, default=0, help="最多處理 N 個文件")
    parser.add_argument("--skip-chm", action="store_true", help="跳過 CHM")
    parser.add_argument("--skip-html", action="store_true", help="跳過 HTML")
    parser.add_argument("--skip-office", action="store_true", help="跳過 Office/PDF")
    args = parser.parse_args()

    print("=" * 60)
    print("Batch Ingest — 全格式批量攝入")
    print("=" * 60)

    # Scan for files
    print("\n[1/3] Scanning for new files...")
    ingested = load_ingested()
    print(f"  Already ingested: {len(ingested)} files")

    # Collect files by type
    chm_files: list[Path] = []
    html_files: list[Path] = []
    office_files: list[Path] = []

    for root in SEARCH_ROOTS:
        if not root.exists():
            continue
        # Use find to enumerate quickly
        for ext, target_list in [(".chm", chm_files),
                                  (".html", html_files), (".htm", html_files),
                                  (".pdf", office_files), (".docx", office_files),
                                  (".pptx", office_files), (".xlsx", office_files),
                                  (".doc", office_files), (".ppt", office_files),
                                  (".xls", office_files)]:
            find_cmd = f'find "{root}" -name "*{ext}" -type f 2>/dev/null'
            try:
                r = subprocess.run(find_cmd, shell=True, capture_output=True,
                                   text=True, timeout=30)
                for p in r.stdout.strip().split("\n"):
                    if p and Path(p).exists():
                        fpath = str(Path(p).resolve())
                        if fpath not in ingested:
                            target_list.append(Path(p))
            except Exception:
                pass

    if args.limit > 0:
        chm_files = chm_files[:args.limit]
        html_files = html_files[:max(0, args.limit - len(chm_files))]
        office_files = office_files[:max(0, args.limit - len(chm_files) - len(html_files))]

    total_new = len(chm_files) + len(html_files) + len(office_files)
    print(f"  New: {total_new} files")
    print(f"    CHM:    {len(chm_files)}")
    print(f"    HTML:   {len(html_files)}")
    print(f"    Office: {len(office_files)}")

    if total_new == 0:
        print("\n  Nothing to ingest.")
        return

    if args.dry_run:
        print("\n[Dry-run] 不寫入。")
        return

    # Ingest
    print("\n[2/3] Converting and ingesting...")
    output_dir = KAFED_ROOT / "data" / "ingested_md"
    output_dir.mkdir(parents=True, exist_ok=True)

    ingested_new: set[str] = set()
    total_converted = 0

    # 2a: CHM
    if not args.skip_chm:
        print(f"\n  CHM ({len(chm_files)} files)...")
        for i, chm in enumerate(chm_files):
            print(f"    [{i+1}/{len(chm_files)}] {chm.name}")
            ok = convert_chm(chm, output_dir)
            if ok:
                ingested_new.add(str(chm.resolve()))
                total_converted += 1

    # 2b: HTML
    if not args.skip_html and html_files:
        print(f"\n  HTML ({len(html_files)} files)...")
        for i in range(0, len(html_files), BATCH_SIZE):
            batch = html_files[i:i + BATCH_SIZE]
            ok = convert_with_markitdown(batch, output_dir)
            total_converted += ok
            for f in batch:
                ingested_new.add(str(f.resolve()))
            print(f"    [{min(i+BATCH_SIZE, len(html_files))}/{len(html_files)}] {ok} converted")

    # 2c: Office/PDF (fallback to doc2md CLI)
    if not args.skip_office and office_files:
        print(f"\n  Office/PDF ({len(office_files)} files)...")
        for i, f in enumerate(office_files):
            md_path = output_dir / f"{f.stem}.md"
            result = subprocess.run(
                [str(DOC2MD), "--clean", str(f), str(md_path)],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0 and md_path.exists() and md_path.stat().st_size > 0:
                ingested_new.add(str(f.resolve()))
                total_converted += 1
            if (i + 1) % 20 == 0:
                print(f"    [{i+1}/{len(office_files)}] {total_converted} converted so far")

    # Save ingested log
    all_ingested = ingested | ingested_new
    save_ingested(all_ingested)

    print(f"\n[3/3] Done.")
    print(f"  Converted: {total_converted}/{total_new}")
    print(f"  Total ingested: {len(all_ingested)}")
    print(f"  Output: {output_dir}")

    # Next step: ingest into KAFED ChromaDB
    print(f"\n  Next: python3 scripts/ingest_to_chromadb.py --dir {output_dir}")
    print(f"  (將轉換後的 markdown 攝入 KAFED 向量庫)")


if __name__ == "__main__":
    main()
