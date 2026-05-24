#!/bin/bash
# 攝入 Study Materials 中未被 KAFED 覆蓋的格式
set -e
cd ~/KAFED

OUTDIR="data/ingested_md"
mkdir -p "$OUTDIR"

echo "=========================================="
echo "Step 1/4: CHM → Markdown (11 files)"
echo "=========================================="
find '/mnt/c/users/bzhao/Documents/Study Materials' -name '*.chm' -type f 2>/dev/null | while read f; do
    name=$(basename "$f" .chm)
    echo "  CHM: $name"
    ~/bin/doc2md --chm --clean "$f" > "$OUTDIR/${name}.md" 2>/dev/null || echo "    FAIL"
done
echo "  Done."

echo ""
echo "=========================================="
echo "Step 2/4: HTML Blog Posts → Markdown"
echo "=========================================="
# Find actual blog posts (not /search/label/ pages)
find '/mnt/c/users/bzhao/Documents/Study Materials/Blog Ref/SAP Learning Blog' \
    -name '*.html' -type f 2>/dev/null \
    | grep -v '/search/label/' \
    > /tmp/blog_posts.txt

total=$(wc -l < /tmp/blog_posts.txt)
echo "  Found $total blog posts"

# Process in batches of 100
python3 -u -c "
import json, sys, subprocess
from pathlib import Path

markitdown = str(Path.home() / '.local/venvs/markitdown/bin/python3')
outdir = Path('$OUTDIR')
batch_size = 100

with open('/tmp/blog_posts.txt') as f:
    files = [l.strip() for l in f if l.strip()]

total = len(files)
converted = 0

for i in range(0, total, batch_size):
    batch = files[i:i+batch_size]
    # Build Python script that processes this batch
    script = '''
import sys
sys.path.insert(0, \"$HOME/.local/venvs/markitdown/lib/python3.14/site-packages\")
from markitdown import MarkItDown
md = MarkItDown()
results = []
files = ''' + json.dumps(batch) + '''
for fpath in files:
    try:
        result = md.convert(fpath)
        content = result.text_content[:100000]
        results.append({\"path\": fpath, \"ok\": True, \"len\": len(content), \"content\": content})
    except Exception as e:
        results.append({\"path\": fpath, \"ok\": False, \"error\": str(e)[:200]})
print(json.dumps(results))
'''
    result = subprocess.run(
        [sys.executable, '-c', script],
        capture_output=True, text=True, timeout=180
    )
    if result.returncode != 0:
        print(f'  Batch {i//batch_size+1}: FAIL ({result.stderr[:200]})')
        continue

    try:
        data = json.loads(result.stdout)
        for item in data:
            fpath = Path(item['path'])
            if item['ok'] and item['content'].strip():
                # Use folder structure to create unique names
                rel_parts = list(fpath.relative_to(fpath.parents[2]).parts)[1:]
                md_name = '_'.join(rel_parts).replace('.html', '.md').replace('/', '_')
                with open(outdir / md_name, 'w') as f:
                    f.write(f'# {fpath.stem}\\n\\n')
                    f.write(item['content'])
                converted += 1
        print(f'  Batch {i//batch_size+1}/{(total-1)//batch_size+1}: {len(data)} files, {sum(1 for d in data if d[\"ok\"])} ok')
    except json.JSONDecodeError as e:
        print(f'  Batch {i//batch_size+1}: JSON parse error ({e})')

print(f'\\nConverted: {converted}/{total}')
" 2>&1

echo ""
echo "=========================================="
echo "Step 3/4: DOCX → Markdown"
echo "=========================================="
find '/mnt/c/users/bzhao/Documents/Study Materials' -name '*.docx' -type f 2>/dev/null | while read f; do
    name=$(basename "$f" .docx)
    [[ "$name" == ~\$* ]] && continue  # skip ~$ temp files
    echo "  DOCX: $name"
    ~/bin/doc2md --clean "$f" "$OUTDIR/${name}.md" 2>/dev/null || echo "    FAIL"
done
echo "  Done."

echo ""
echo "=========================================="
echo "Step 4/4: Ingest into KAFED ChromaDB"
echo "=========================================="
cd ~/KAFED
.venv/bin/python3 -u scripts/batch_ingest_to_kafed.py "$OUTDIR" 2>&1 || echo "WARNING: ChromaDB ingest had errors"

echo ""
echo "Done. All new formats ingested."
