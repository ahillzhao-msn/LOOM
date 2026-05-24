#!/usr/bin/env python3
"""Inline batch convert SAP Learning Blog HTML → markdown. Single process, no subprocess nesting."""
import json, os, sys, time, glob

# Ensure markitdown is importable
sys.path.insert(0, os.path.expanduser("~/.local/venvs/markitdown/lib/python3.14/site-packages"))
sys.stdout.reconfigure(line_buffering=True)

from markitdown import MarkItDown

BLOG_DIR = "/mnt/c/users/bzhao/Documents/Study Materials/Blog Ref"
OUTDIR = os.path.expanduser("~/KAFED/data/ingested_md")
BATCH_SIZE = 50
os.makedirs(OUTDIR, exist_ok=True)

# Find files
print("Scanning...")
files = []
for root, dirs, names in os.walk(BLOG_DIR):
    for n in names:
        if n.endswith(".html") and "/search/label/" not in root:
            files.append(os.path.join(root, n))

print(f"Found {len(files)} files")

md = MarkItDown()
t0 = time.time()
converted = 0
errors = 0

for i in range(0, len(files), BATCH_SIZE):
    batch = files[i:i+BATCH_SIZE]
    bt0 = time.time()
    for fp in batch:
        try:
            r = md.convert(fp)
            content = r.text_content
            if content.strip():
                # Derive safe filename
                rel = os.path.relpath(fp, BLOG_DIR)
                safe = rel.replace(os.sep, "_").replace(".html", ".md")
                dest = os.path.join(OUTDIR, safe)
                with open(dest, "w", encoding="utf-8") as f:
                    f.write(content)
                converted += 1
            else:
                errors += 1
        except Exception as e:
            errors += 1

    bt = time.time() - bt0
    elapsed = time.time() - t0
    done = min(i + BATCH_SIZE, len(files))
    rate = done / elapsed if elapsed > 0 else 1
    remaining = (len(files) - done) / rate if rate > 0 else 0
    print(f"[{done}/{len(files)}] +{len(batch)} files ({bt:.1f}s), "
          f"{elapsed:.0f}s elapsed, ~{remaining:.0f}s remaining, {converted} ok, {errors} err")

total = time.time() - t0
print(f"\nDone in {total:.0f}s: {converted} converted, {errors} errors")
