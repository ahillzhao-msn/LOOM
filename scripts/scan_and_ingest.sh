#!/usr/bin/env bash
# Knowledge Ingestion — 全格式攝入管道
# 舊名 batch_ingest_pdfs.sh → 改為 scan_and_ingest.sh
#
# 自動檢測文件格式，調用相應管道攝入 KAFED。
#
# 支援:
#   doc2md 直接格式: pdf, docx, pptx, xlsx, html, txt, md, csv, json, xml
#   圖片 OCR:        png, jpg, jpeg, tiff
#   特殊管道:        chm (extract_chm → doc2md)
#                    mp4 (transcribe → text)
#
# 用法:
#   scan_and_ingest.sh [--dry-run] [--limit N] [<directory>]

set -euo pipefail

DRY_RUN=false
LIMIT=0
TARGET_DIR=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY_RUN=true; shift ;;
        --limit) LIMIT="$2"; shift 2 ;;
        *) TARGET_DIR="$1"; shift ;;
    esac
done

KAFED_DIR="$HOME/KAFED"
VENV="$KAFED_DIR/.venv"
LOG_DIR="$KAFED_DIR/data/logs/ingestion"
mkdir -p "$LOG_DIR"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG="$LOG_DIR/ingest_$TIMESTAMP.log"

echo "[$(date)] Knowledge Ingestion Pipeline" | tee -a "$LOG"
echo "  Target: ${TARGET_DIR:-all Study Materials}" | tee -a "$LOG"
echo "  Dry-run: $DRY_RUN" | tee -a "$LOG"
echo "  Limit: ${LIMIT:-none}" | tee -a "$LOG"
echo "" | tee -a "$LOG"

# Build scan command
SCAN_CMD="$VENV/bin/python3 $KAFED_DIR/scripts/knowledge_scanner.py"
if [ -n "$TARGET_DIR" ]; then
    SCAN_CMD="$SCAN_CMD --root $TARGET_DIR"
fi
SCAN_CMD="$SCAN_CMD --output /tmp/knowledge_scan_$TIMESTAMP.json"

echo "[1/3] Scanning..." | tee -a "$LOG"
eval "$SCAN_CMD" 2>&1 | tee -a "$LOG"

if $DRY_RUN; then
    echo "[DRY-RUN] Stopping after scan." | tee -a "$LOG"
    exit 0
fi

echo "[2/3] Ingesting known formats..." | tee -a "$LOG"

# Read scan results and ingest
python3 - "$TIMESTAMP" "$LIMIT" << 'PYEOF' 2>&1 | tee -a "$LOG"
import json, sys, subprocess, os
from pathlib import Path

timestamp = sys.argv[1]
limit = int(sys.argv[2]) if sys.argv[2] else 0

report_path = Path(f"/tmp/knowledge_scan_{timestamp}.json")
if not report_path.exists():
    print("  [ERROR] No scan report found")
    sys.exit(1)

with open(report_path) as f:
    report = json.load(f)

files = report.get("files", [])
total = len(files)
print(f"  Files to ingest: {total}")

# Sort: start with doc2md-native formats first
direct_exts = {'.pdf', '.docx', '.pptx', '.xlsx', '.html', '.htm',
               '.txt', '.md', '.csv', '.json', '.xml'}

ingested = 0
for entry in files:
    ext = entry.get("format", "")
    path = entry.get("path", "")
    
    # Skip special formats (CHM, MP4, etc.) — handled separately
    if ext not in direct_exts:
        continue
    
    if limit and ingested >= limit:
        print(f"  Reached limit ({limit}), stopping")
        break
    
    # Skip files already in KAFED (check by path hash)
    # TODO: track ingested files via DB
    
    cmd = f"doc2md --clean '{path}'"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
    if result.returncode == 0:
        ingested += 1
        if ingested % 50 == 0:
            print(f"  Progress: {ingested}/{total}")
    else:
        print(f"  [FAIL] {path}: {result.stderr[:100]}")

print(f"\n  Ingested: {ingested}/{total} files")
PYEOF

echo "[3/3] Summary" | tee -a "$LOG"
echo "  Log: $LOG" | tee -a "$LOG"
echo "  Done: $(date)" | tee -a "$LOG"
