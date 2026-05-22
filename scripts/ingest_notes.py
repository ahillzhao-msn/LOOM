#!/usr/bin/env python3
"""
攝入 NOTES 目錄到 KAFED。
使用 KAFED ingest() 的自動分類（classify）推導領域。
"""

import sys
import time
from pathlib import Path

KAFED_SRC = Path.home() / "km" / "kafed" / "src"
sys.path.insert(0, str(KAFED_SRC))

# ── 導入本地後端 ──
# 使用 Hermes venv 的 python 時自動載入 GPU embedding
from kafed.client.local_backend import KafedLocalBackend

NOTES_ROOT = Path(os.getenv("NOTES_PATH", str(Path.home() / "Documents" / "NOTES")))
CONVERTED_DIR = Path.home() / ".hermes" / "data" / "converted"
INGESTED_LOG = Path.home() / ".hermes" / "data" / "ingested_notes.log"

def convert_to_md(src_path: Path) -> str | None:
    """用 doc2md 轉換非 MD 文件，回傳 markdown 路徑或 None。"""
    import subprocess
    
    # 已有 markdown 的不用轉
    if src_path.suffix.lower() in (".md", ".markdown", ".txt"):
        return str(src_path)
    
    # doc2md 路線
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
    ingested = set()
    if INGESTED_LOG.exists():
        with open(INGESTED_LOG) as f:
            ingested = {line.strip() for line in f if line.strip()}
    
    # 掃描所有可處理文件
    extensions = {".pdf", ".docx", ".pptx", ".html", ".htm", ".txt",
                  ".md", ".markdown", ".csv"}
    files = sorted([
        f for f in NOTES_ROOT.rglob("*")
        if f.suffix.lower() in extensions and f.is_file()
        and not any(p.startswith(".") for p in f.parts)  # 跳過隱藏目錄
        and f.stat().st_size > 50  # 跳過空文件
    ])
    
    # 過濾已攝入
    pending = [f for f in files if str(f) not in ingested]
    
    print(f"NOTES 攝入 — {len(files)} 總文件, {len(pending)} 待處理")
    print(f"  (跳過 {len(files) - len(pending)} 已攝入)")
    print()
    
    success = 0
    fail = 0
    skipped = 0
    total_chunks = 0
    
    for i, src in enumerate(pending, 1):
        size_kb = src.stat().st_size / 1024
        path_display = str(src.relative_to(NOTES_ROOT))
        print(f"  [{i}/{len(pending)}] {path_display[:60]:60s} ({size_kb:.0f}KB)", end="")
        
        # 轉換成 doc2md 可讀格式
        md_path = convert_to_md(src)
        if md_path is None:
            print("  ⏭ 無法轉換")
            skipped += 1
            continue
        
        # 攝入（自動分類）
        t0 = time.time()
        try:
            result = bridge.ingest(md_path)  # domain=None → auto classify
            elapsed = time.time() - t0
            status = result.get("status", "error")
            chunks = result.get("chunks", 0)
            
            if status == "ok" and chunks > 0:
                domain = result.get("domain", "?")
                print(f"  ✅ → {domain:15s} {chunks:4d} chunks ({elapsed:.1f}s)")
                success += 1
                total_chunks += chunks
                # 記錄已攝入
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
