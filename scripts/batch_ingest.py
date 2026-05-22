#!/usr/bin/env python3
"""KAFED batch ingestion script.

Convert PDF -> Markdown -> KAFED vector store.

Usage:
    python batch_ingest.py --dir "Study Materials/PM" --domain SAP_PM
    python batch_ingest.py --dir "Study Materials/SAP Press" --domain SAP_PRESS
    python batch_ingest.py --all
"""
import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from kafed.client.local_backend import KafedLocalBackend

BACKEND = KafedLocalBackend()
MODE = "local"

DOCUMENTS_ROOT = Path(os.getenv("DOCUMENTS_ROOT", str(Path.home() / "Documents")))

STUDY_DIRS = {
    "PM": "Study Materials/PM",
    "SAP Press": "Study Materials/SAP Press",
    "ABAP": "Study Materials/ABAP",
    "SCM": "Study Materials/SCM",
    "PS": "Study Materials/PS",
    "IS-U": "Study Materials/IS-U",
}

def main():
    ap = argparse.ArgumentParser(description="KAFED batch ingestion")
    ap.add_argument("--dir", help=f"Relative dir under Documents/. Known: {list(STUDY_DIRS.keys())}")
    ap.add_argument("--domain", default="GENERAL", help="Knowledge domain")
    ap.add_argument("--all", action="store_true", help="Ingest all known dirs")
    args = ap.parse_args()

    if args.all:
        for name, rel in STUDY_DIRS.items():
            d = DOCUMENTS_ROOT / rel
            if d.exists():
                print(f"\n=== {name} ({d}) ===")
                ingest_dir(d, name.upper().replace(" ", "_"))
        return

    if args.dir:
        path = Path(args.dir)
        if not path.is_absolute():
            path = DOCUMENTS_ROOT / args.dir
        ingest_dir(path, args.domain)
        return

    ap.print_help()

def ingest_dir(directory: Path, domain: str):
    pdfs = list(directory.glob("**/*.pdf")) + list(directory.glob("**/*.PDF"))
    print(f"Found {len(pdfs)} PDFs")
    for i, pdf in enumerate(pdfs, 1):
        print(f"  [{i}/{len(pdfs)}] {pdf.name}...")
        try:
            result = subprocess.run(
                ["doc2md", str(pdf)],
                capture_output=True, text=True, timeout=600
            )
            if result.returncode != 0 or not result.stdout.strip():
                print(f"    SKIP (empty output)")
                continue
            r = BACKEND.ingest_text(result.stdout, filename=pdf.name, domain=domain)
            print(f"    OK ({r.get('chunks', 0)} chunks)")
        except Exception as e:
            print(f"    ERROR: {e}")
        time.sleep(0.5)

if __name__ == "__main__":
    main()
