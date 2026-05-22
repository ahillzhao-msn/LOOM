#!/usr/bin/env python3
"""
攝入 Issue List 目錄到 KAFED。
全掃 + 自動過濾非文本。增量（已攝入的跳過）。
"""

import subprocess
import sys
import time
import os
from pathlib import Path

KAFED_SRC = Path.home() / "km" / "kafed" / "src"
sys.path.insert(0, str(KAFED_SRC))
from kafed.client.local_backend import KafedLocalBackend

ISSUE_ROOT = Path(os.getenv("ISSUE_LIST_PATH", str(Path.home() / "Documents" / "Issue List")))
CONVERTED_DIR = Path.home() / ".hermes" / "data" / "converted"
INGESTED_LOG = Path.home() / ".hermes" / "data" / "ingested_issue_list.log"

# 可提取文字的文件類型
TEXT_EXTENSIONS = {".pdf", ".docx", ".doc", ".pptx", ".ppt",
                   ".txt", ".md", ".markdown", ".html", ".htm",
                   ".csv", ".rtf", ".odt"}

# 跳過的巨量目錄（內含大量 CAD/shapefile/圖片，無文字價值）
SKIP_DIRS = {
    "Facility Work Request",  # 27,875 files, mostly CAD + images
    "GIS GNN And LLM",       # 3,201 files, GIS data
    "CSP Project",           # 6,392 files, mixed
}

def is_text_file(path: Path) -> bool:
    """快速檢查是否為可提取文字的檔案類型。"""
    return path.suffix.lower() in TEXT_EXTENSIONS

def convert_to_md(src_path: Path) -> str | None:
    """用 doc2md 轉換非 MD 文件。"""
    if src_path.suffix.lower() in (".txt", ".md", ".markdown", ".csv"):
        return str(src_path)  # 不用轉換

    doc2md = Path.home() / "bin" / "doc2md"
    out_name = src_path.name + ".md"
    out_path = CONVERTED_DIR / out_name

    if out_path.exists() and out_path.stat().st_mtime >= src_path.stat().st_mtime:
        return str(out_path)  # 快取可用

    try:
        result = subprocess.run(
            [str(doc2md), "--clean", str(src_path), str(out_path)],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0 and out_path.exists() and out_path.stat().st_size > 50:
            return str(out_path)
        return None
    except Exception:
        return None


def main():
    bridge = KafedLocalBackend()

    # 載入已攝入記錄
    ingested = set()
    if INGESTED_LOG.exists():
        with open(INGESTED_LOG) as f:
            ingested = {line.strip() for line in f if line.strip()}

    # 用 os.scandir 手動迭代（跳過巨量目錄，快於 rglob/find）
    print("掃描 Issue List 中...")
    files = []
    for entry in ISSUE_ROOT.iterdir():
        if entry.name in SKIP_DIRS or entry.name.startswith("."):
            continue
        if entry.is_dir():
            # 限制每目錄掃描深度
            for dirpath, dirnames, filenames in os.walk(str(entry), topdown=True):
                # 限制深度為 4 層
                depth = dirpath.replace(str(entry), "").count(os.sep)
                if depth >= 4:
                    dirnames.clear()
                    continue
                # 跳過隱藏目錄
                dirnames[:] = [d for d in dirnames if not d.startswith(".") and not d.startswith("~$")]
                for fn in filenames:
                    if fn.startswith("~$") or fn.startswith("."):
                        continue
                    ext = Path(fn).suffix.lower()
                    if ext in TEXT_EXTENSIONS:
                        fp = Path(dirpath) / fn
                        try:
                            if fp.stat().st_size > 50:
                                files.append(fp)
                        except OSError:
                            continue
        elif entry.is_file():
            ext = entry.suffix.lower()
            if ext in TEXT_EXTENSIONS and entry.stat().st_size > 50:
                files.append(entry)
    files.sort()

    print(f"  掃描完成: {len(files)} 個文字文件")
    # 過濾已攝入
    pending = [f for f in files if str(f) not in ingested]

    print(f"  總文字文件: {len(files)}")
    print(f"  待攝入: {len(pending)}")
    print(f"  已攝入: {len(files) - len(pending)}")
    print()

    if not pending:
        print("沒有新文件。")
        return

    success = 0
    fail = 0
    skipped = 0
    total_chunks = 0

    for i, src in enumerate(pending, 1):
        size_kb = src.stat().st_size / 1024
        path_display = str(src.relative_to(ISSUE_ROOT))[:65]
        print(f"  [{i}/{len(pending)}] {path_display:65s} ({size_kb:.0f}KB)", end="")

        md_path = convert_to_md(src)
        if md_path is None:
            print("  ⏭ 無法轉換")
            skipped += 1
            continue

        t0 = time.time()
        try:
            result = bridge.ingest(md_path)  # auto-classify
            elapsed = time.time() - t0
            status = result.get("status", "error")
            chunks = result.get("chunks", 0)

            if status == "ok" and chunks > 0:
                domain = result.get("domain", "?")
                print(f"  ✅ → {domain:15s} {chunks:4d} chunks ({elapsed:.1f}s)")
                success += 1
                total_chunks += chunks
                with open(INGESTED_LOG, "a") as f:
                    f.write(str(src) + "\n")
            elif status == "warning":
                print(f"  ⚠️ 0 chunks (品質過濾)")
                skipped += 1
                with open(INGESTED_LOG, "a") as f:
                    f.write(str(src) + "\n")
            else:
                print(f"  ❌ {result.get('message', '未知錯誤')}")
                fail += 1
        except Exception as e:
            elapsed = time.time() - t0
            print(f"  ❌ {str(e)[:60]}")
            fail += 1

    print()
    print(f"=== 完成 ===")
    print(f"  成功: {success} | 失敗: {fail} | 跳過: {skipped}")
    print(f"  新增 chunks: {total_chunks}")
    final = bridge.stats()
    print(f"  KAFED 總計: {final['total_chunks']} chunks")


if __name__ == "__main__":
    main()
