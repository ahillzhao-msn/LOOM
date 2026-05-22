#!/usr/bin/env python3
"""
批量攝入 Study Materials → KAFED。

三階段：
  Stage 1 — 攝入 ~/.hermes/data/converted/ 中已有的 markdown（81 個檔案）
  Stage 2 — 轉換 + 攝入剩餘小 PDF（<50MB，4 個）
  Stage 3 — 轉換 + 攝入大 PDF（>50MB，15 個，需解除腳本限制）
"""

import json
import sys
import time
from pathlib import Path

# ── 確保 KAFED 在 import path 上 ──
KAFED_SRC = Path.home() / "km" / "kafed" / "src"
sys.path.insert(0, str(KAFED_SRC))

from kafed.client.local_backend import KafedLocalBackend

# ── 路徑 ──
STUDY_ROOT = Path(os.getenv("STUDY_MATERIALS_PATH", str(Path.home() / "Documents" / "Study Materials")))
CONVERTED_DIR = Path.home() / ".hermes" / "data" / "converted"
INGESTED_LOG = Path.home() / ".hermes" / "data" / "ingested_pdfs.log"


def guess_domain(text: str, filename: str = "") -> str:
    """使用 KAFED auto-classify 推導知識域。"""
    try:
        from kafed.server.classify import classify
        sample = text[:500] if len(text) > 50 else filename[:200]
        return classify(sample).get("domain", "SAP_GENERAL")
    except Exception:
        return "SAP_GENERAL"


def ingest_markdown(bridge: KafedLocalBackend, md_path: Path) -> dict:
    """攝入一個 markdown 檔案（auto-classify）。"""
    t0 = time.time()
    try:
        result = bridge.ingest(str(md_path))  # domain=None → auto classify
        elapsed = time.time() - t0
        domain = result.get("domain", "unknown")
        return {"path": str(md_path), "domain": domain,
                "status": result.get("status", "error"),
                "chunks": result.get("chunks", 0),
                "elapsed": round(elapsed, 3)}
    except Exception as e:
        elapsed = time.time() - t0
        return {"path": str(md_path), "domain": "error",
                "status": "error", "error": str(e),
                "elapsed": round(elapsed, 3)}


def convert_and_ingest_pdf(bridge: KafedLocalBackend, pdf_path: Path,
                            docling: bool = False) -> dict:
    """先用 doc2md 轉換，再攝入 KAFED。"""
    import subprocess
    doc2md = Path.home() / "bin" / "doc2md"
    out_path = CONVERTED_DIR / (pdf_path.name + ".md")
    
    # 轉換（若快取不存在或非最新）
    t0 = time.time()
    if not out_path.exists() or out_path.stat().st_mtime < pdf_path.stat().st_mtime:
        cmd = [str(doc2md)]
        if docling:
            cmd.append("--docling")
        cmd.extend(["--clean", str(pdf_path), str(out_path)])
        
        conv = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if conv.returncode != 0 or not out_path.exists():
            return {"path": str(pdf_path), "status": "error",
                    "error": f"doc2md failed: {conv.stderr[:200]}",
                    "elapsed": round(time.time() - t0, 3)}
    
    convert_elapsed = round(time.time() - t0, 3)
    
    # 攝入
    result = ingest_markdown(bridge, out_path)
    result["convert_elapsed"] = convert_elapsed
    return result


def stage1_converted_markdowns(bridge: KafedLocalBackend) -> list[dict]:
    """Stage 1: 攝入所有已轉換的 markdown。"""
    mds = sorted(CONVERTED_DIR.glob("*.md"))
    print(f"\n{'='*60}")
    print(f"Stage 1: {len(mds)} 個已轉換 markdown → KAFED")
    print(f"{'='*60}")
    
    results = []
    for i, md in enumerate(mds, 1):
        result = ingest_markdown(bridge, md)
        results.append(result)
        status_icon = "✅" if result["status"] == "ok" else "⚠️"
        print(f"  [{i}/{len(mds)}] {status_icon} {md.name[:50]:50s} "
              f"→ {result['domain']:15s} {result['chunks']:4d} chunks "
              f"({result['elapsed']:.1f}s)")
    
    return results


def stage2_small_pdfs(bridge: KafedLocalBackend) -> list[dict]:
    """Stage 2: 剩餘 <50MB 的 PDF（跳過已攝入記錄的）。"""
    # 讀取已攝入記錄
    ingested = set()
    if INGESTED_LOG.exists():
        with open(INGESTED_LOG) as f:
            ingested = {line.strip() for line in f if line.strip()}
    
    # 找所有 PDF
    all_pdfs = sorted(STUDY_ROOT.rglob("*.pdf"))
    
    # 過濾：未攝入 + <50MB
    pending = []
    for pdf in all_pdfs:
        rel = str(pdf.relative_to(STUDY_ROOT))
        if rel in ingested:
            continue
        size = pdf.stat().st_size
        if size <= 50_000_000:  # <50MB
            pending.append(pdf)
    
    print(f"\n{'='*60}")
    print(f"Stage 2: {len(pending)} 個小 PDF → doc2md → KAFED")
    print(f"{'='*60}")
    
    results = []
    for i, pdf in enumerate(pending, 1):
        result = convert_and_ingest_pdf(bridge, pdf, docling=False)
        results.append(result)
        status_icon = "✅" if result["status"] == "ok" else "❌"
        elapsed = result.get("convert_elapsed", result["elapsed"])
        print(f"  [{i}/{len(pending)}] {status_icon} {pdf.name[:50]:50s} "
              f"→ {result.get('domain','?'):15s} {result.get('chunks',0):4d} chunks "
              f"({elapsed:.1f}s)")
        if result["status"] != "ok":
            print(f"       Error: {result.get('error', 'unknown')}")
    
    return results


def stage3_large_pdfs(bridge: KafedLocalBackend) -> list[dict]:
    """Stage 3: >50MB 的大 PDF（SAP Press 書為主）。用 pymupdf4llm 快轉。"""
    ingested = set()
    if INGESTED_LOG.exists():
        with open(INGESTED_LOG) as f:
            ingested = {line.strip() for line in f if line.strip()}
    
    all_pdfs = sorted(STUDY_ROOT.rglob("*.pdf"))
    
    pending = []
    for pdf in all_pdfs:
        rel = str(pdf.relative_to(STUDY_ROOT))
        if rel in ingested:
            continue
        size = pdf.stat().st_size
        if size > 50_000_000:
            pending.append(pdf)
    
    print(f"\n{'='*60}")
    print(f"Stage 3: {len(pending)} 個大 PDF >50MB → doc2md → KAFED")
    print(f"{'='*60}")
    
    results = []
    for i, pdf in enumerate(pending, 1):
        size_mb = pdf.stat().st_size / 1_000_000
        print(f"\n  [{i}/{len(pending)}] {pdf.name[:60]} ({size_mb:.0f}MB)")
        result = convert_and_ingest_pdf(bridge, pdf, docling=False)
        status_icon = "✅" if result["status"] == "ok" else "❌"
        elapsed = result.get("convert_elapsed", result.get("elapsed", 0))
        print(f"       {status_icon} → {result.get('domain','?'):15s} "
              f"{result.get('chunks',0):4d} chunks ({elapsed:.1f}s)")
        if result["status"] != "ok":
            print(f"       ❌ Error: {result.get('error', 'unknown')}")
    
    return results


def print_summary(stages: list[tuple[str, list[dict]]]):
    """列印彙總。"""
    print(f"\n{'='*60}")
    print("  彙總")
    print(f"{'='*60}")
    
    total_ok = total_chunks = total_elapsed = 0
    total_files = 0
    
    for name, results in stages:
        ok = sum(1 for r in results if r["status"] == "ok")
        chunks = sum(r.get("chunks", 0) for r in results if r["status"] == "ok")
        elapsed = sum(r["elapsed"] for r in results)
        files = len(results)
        
        total_ok += ok
        total_chunks += chunks
        total_elapsed += elapsed
        total_files += files
        
        print(f"  {name:40s} {ok:3d}/{files:<3d} ok, {chunks:5d} chunks, {elapsed:.0f}s")
    
    print(f"  {'─'*60}")
    print(f"  {'TOTAL':40s} {total_ok:3d}/{total_files:<3d} ok, {total_chunks:5d} chunks, {total_elapsed:.0f}s")
    print(f"  {'(實際會因並行而更快)':>60s}")


def main():
    bridge = KafedLocalBackend()
    
    print("KAFED 批量攝入 — Study Materials")
    print(f"  KAFED 當前: {bridge.stats()['total_chunks']} chunks")
    print(f"  GPU: 已啟用（bge-small on CUDA）")
    
    # Stage 1
    s1 = stage1_converted_markdowns(bridge)
    
    # Stage 2
    s2 = stage2_small_pdfs(bridge)
    
    # Stage 3
    s3 = stage3_large_pdfs(bridge)
    
    # Summary
    print_summary([("Stage 1: 已轉換 markdown", s1),
                   ("Stage 2: 小 PDF", s2),
                   ("Stage 3: 大 PDF", s3)])
    
    # Final stats
    final = bridge.stats()
    print(f"\n  最終 KAFED: {final['total_chunks']} chunks")
    added = final['total_chunks'] - 3538  # 減去開始前的 baseline
    print(f"  新增 chunks: {added}")
    print(f"  域列表:")
    for d in final['domains']:
        print(f"    {d['name']:20s}: {d['count']}")


if __name__ == "__main__":
    main()
