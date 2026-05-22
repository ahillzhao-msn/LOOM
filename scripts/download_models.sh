#!/usr/bin/env bash
# KAFED 模型下載腳本
# 預下載 embedding 模型，避免首次查詢時的下載延遲
# 用法: bash scripts/download_models.sh

set -euo pipefail

echo "== KAFED 模型下載 =="

# 激活虛擬環境（如果存在）
if [ -d "$(dirname "$0")/../.venv" ]; then
    source "$(dirname "$0")/../.venv/bin/activate"
    echo "  ✅ 虛擬環境已激活"
fi

echo ""
echo "[1/1] 下載 embedding 模型"
python3 -c "
from sentence_transformers import SentenceTransformer
model = SentenceTransformer('BAAI/bge-small-en-v1.5')
print(f'  模型: {model._modules[\"0\"].auto_model.config._name_or_path}')
print(f'  維度: {model.get_sentence_embedding_dimension()}')
print(f'  設備: {model._target_device}')
"
echo "  ✅ 模型下載完成"
echo ""
echo "模型快取位置: ~/.cache/huggingface/hub/"
