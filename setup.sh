#!/usr/bin/env bash
# KAFED 一鍵安裝腳本
# 用法: bash setup.sh

set -euo pipefail

KAFED_ROOT="$(cd "$(dirname "$0")" && pwd)"
KAFED_DATA_DIR="${KAFED_DATA_DIR:-$HOME/.kafed}"

echo "== KAFED 安裝 =="
echo "  根目錄: $KAFED_ROOT"
echo "  數據目錄: $KAFED_DATA_DIR"
echo ""

# 1. Python 環境檢查
echo "[1/5] Python 環境檢查"
PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" &>/dev/null; then
    echo "  ❌ 未找到 Python：$PYTHON"
    echo "  請安裝 Python 3.10+ 或設置 PYTHON 環境變量"
    exit 1
fi
PY_VER=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "  ✅ Python $PY_VER ($(which "$PYTHON"))"

# 2. 創建虛擬環境
echo "[2/5] 虛擬環境"
if [ ! -d "$KAFED_ROOT/.venv" ]; then
    "$PYTHON" -m venv "$KAFED_ROOT/.venv"
    echo "  ✅ 已創建 .venv"
else
    echo "  ✅ .venv 已存在"
fi
source "$KAFED_ROOT/.venv/bin/activate"
echo "  ✅ 已激活虛擬環境"

# 3. 安裝依賴
echo "[3/5] 安裝 Python 依賴"
pip install -U pip --quiet
pip install -e "$KAFED_ROOT" --quiet
echo "  ✅ KAFED 已安裝"
echo "  ✅ 運行 pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu 安裝 CPU 版 PyTorch"
echo "  ✅ 運行 pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121 安裝 CUDA 版 PyTorch"

# 4. 創建數據目錄
echo "[4/5] 創建數據目錄"
mkdir -p "$KAFED_DATA_DIR/data/chroma"
mkdir -p "$KAFED_DATA_DIR/data/feedback_logs"
mkdir -p "$KAFED_DATA_DIR/data/logs"
mkdir -p "$KAFED_DATA_DIR/data/kpak"
mkdir -p "$KAFED_DATA_DIR/finder_context"
echo "  ✅ 數據目錄: $KAFED_DATA_DIR"

# 5. 配置模板
echo "[5/5] 配置模板"
if [ ! -f "$KAFED_ROOT/kafed.yaml" ]; then
    if [ -f "$KAFED_ROOT/kafed.yaml.example" ]; then
        cp "$KAFED_ROOT/kafed.yaml.example" "$KAFED_ROOT/kafed.yaml"
        echo "  ✅ 已創建 kafed.yaml（需編輯配置）"
    fi
fi
if [ ! -f "$KAFED_ROOT/.env" ]; then
    if [ -f "$KAFED_ROOT/.env.example" ]; then
        cp "$KAFED_ROOT/.env.example" "$KAFED_ROOT/.env"
        echo "  ✅ 已創建 .env（需填入 API 密鑰）"
    fi
fi

echo ""
echo "== 安裝完成 =="
echo "  使用: source $KAFED_ROOT/.venv/bin/activate"
echo "  配置: 編輯 $KAFED_ROOT/kafed.yaml"
echo "  密鑰: 編輯 $KAFED_ROOT/.env"
echo ""
echo "  測試: cd $KAFED_ROOT && python -c 'from kafed.config import get_config; print(get_config().show())'"
