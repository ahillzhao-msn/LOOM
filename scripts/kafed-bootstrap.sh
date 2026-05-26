#!/usr/bin/env bash
#
# KAFED Bootstrap — 一鍵安裝+初始化腳本
#
# 用法：
#   curl -fsSL https://raw.githubusercontent.com/... | bash
#   bash <(curl -fsSL ...)
#   # 或本地：
#   cd KAFED && bash scripts/kafed-bootstrap.sh
#
# 功能：
#   1. 檢測環境（Hermes/WSL/GPU/llama-server）
#   2. 自動生成 kafed.yaml（自適應配置）
#   3. 創建數據目錄 + 初始化所有模塊
#   4. 註冊 cron 任務
#   5. 安裝到 Hermes venv（默認）或獨立 venv
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── 顏色 ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()   { echo -e "${GREEN}[✓]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
err()   { echo -e "${RED}[✗]${NC} $1"; }
info()  { echo -e "${BLUE}[·]${NC} $1"; }

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  KAFED Bootstrap — 一鍵安裝初始化       ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ══════════════════════════════════════════════════
# Step 1: 確認 Python >= 3.10
# ══════════════════════════════════════════════════

PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        VER=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)
        MAJOR=$(echo "$VER" | cut -d. -f1)
        MINOR=$(echo "$VER" | cut -d. -f2)
        if [ "$MAJOR" -ge 3 ] && [ "$MINOR" -ge 10 ]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    err "需要 Python >= 3.10（未找到）"
    exit 1
fi
log "Python: $($PYTHON --version 2>&1)"

# ══════════════════════════════════════════════════
# Step 2: 檢測 Hermes venv
# ══════════════════════════════════════════════════

HERMES_VENV=""
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"

if command -v hermes &>/dev/null; then
    log "Hermes CLI 可用"
    # 試探 Hermes venv
    if [ -f "$HERMES_HOME/.venv/bin/python3" ]; then
        HERMES_VENV="$HERMES_HOME/.venv"
    elif [ -f "$HERMES_HOME/venv/bin/python3" ]; then
        HERMES_VENV="$HERMES_HOME/venv"
    fi
elif [ -f "$HERMES_HOME/.venv/bin/python3" ]; then
    log "發現 Hermes venv: $HERMES_HOME/.venv"
    HERMES_VENV="$HERMES_HOME/.venv"
else
    warn "Hermes 未檢測到——將使用獨立 venv"
fi

# ══════════════════════════════════════════════════
# Step 3: 安裝 KAFED
# ══════════════════════════════════════════════════

INSTALL_TARGET="standalone"
PIP_CMD="$PYTHON -m pip"

if [ -n "$HERMES_VENV" ]; then
    INSTALL_TARGET="hermes"
    PIP_CMD="$HERMES_VENV/bin/python3 -m pip"
    log "安裝目標: Hermes venv ($HERMES_VENV)"
else
    # 創建獨立 venv
    if [ ! -d "$PROJECT_ROOT/.venv" ]; then
        info "創建獨立 venv..."
        $PYTHON -m venv "$PROJECT_ROOT/.venv"
    fi
    PIP_CMD="$PROJECT_ROOT/.venv/bin/python3 -m pip"
    log "安裝目標: 獨立 venv ($PROJECT_ROOT/.venv)"
fi

info "安裝 KAFED 包 ($PROJECT_ROOT)..."
$PIP_CMD install -e "$PROJECT_ROOT" 2>&1 | tail -1
log "KAFED 安裝完成"

# ══════════════════════════════════════════════════
# Step 4: 運行 Bootstrap
# ══════════════════════════════════════════════════

BOOTSTRAP_PY="$PIP_CMD"
if echo "$PIP_CMD" | grep -q "python3"; then
    BOOTSTRAP_PY=$(echo "$PIP_CMD" | sed 's/ -m pip//')
fi

info "運行 KAFED Bootstrap 初始化..."
if [ -n "$HERMES_VENV" ]; then
    $HERMES_VENV/bin/python3 -m kafed.install.bootstrap --auto --hermes
else
    $PROJECT_ROOT/.venv/bin/python3 -m kafed.install.bootstrap --auto --venv
fi

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  KAFED 初始化完成！                       ║"
echo "╚══════════════════════════════════════════╝"
echo ""
info "下一步："
echo "  驗證安裝:  kafed-init"
echo "  啟動心跳:  kafed-heartbeat"
echo "  查看配置:  kafed config show  (或 ~/.kafed/kafed.yaml)"
echo ""
echo "  需要攝入知識文檔？"
echo "    python3 -m kafed.ingest  <file-or-dir>"
echo ""
