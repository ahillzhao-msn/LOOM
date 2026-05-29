#!/bin/bash
# LOOM Hermes Tool Symlink Installer
# 將 LOOM 工具註冊到 Hermes 的 tools/ 目錄
# 建立 symlink 後，Hermes 在下次重啟時透過 AST auto-discovery 自動註冊

set -e

LOOM_PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LOOM_TOOL_SRC="${LOOM_PROJECT_ROOT}/src/loom/tools/hermes_tools.py"
HERMES_TOOLS_DIR="${HOME}/.hermes/hermes-agent/tools"

# 交替檢查：若 HERMES_HOME 環境變量設置了自定義路徑
if [ -n "${HERMES_HOME}" ]; then
    HERMES_TOOLS_DIR="${HERMES_HOME}/hermes-agent/tools"
fi

if [ ! -f "$LOOM_TOOL_SRC" ]; then
    echo "ERROR: LOOM tools not found at: $LOOM_TOOL_SRC"
    exit 1
fi

mkdir -p "$HERMES_TOOLS_DIR"

# 移除舊 symlink（若存在）
rm -f "${HERMES_TOOLS_DIR}/loom_tool.py"

# 建立新 symlink
ln -sf "$LOOM_TOOL_SRC" "${HERMES_TOOLS_DIR}/loom_tool.py"

echo "✓ LOOM tools symlinked:"
echo "  ${HERMES_TOOLS_DIR}/loom_tool.py → ${LOOM_TOOL_SRC}"

# 使用 LOOM venv 或系統 Python 驗證
LOOM_VENV="${LOOM_PROJECT_ROOT}/.venv"
if [ -f "${LOOM_VENV}/bin/python3" ]; then
    PYTHON="${LOOM_VENV}/bin/python3"
else
    PYTHON="python3"
fi

echo ""
echo "  Verifying from LOOM venv..."
if $PYTHON -c "
from loom.tools.hermes_tools import loom_recommend, loom_solidify, loom_status
assert callable(loom_recommend)
assert callable(loom_solidify)
assert callable(loom_status)
print('  ✓ Function imports: OK')
" 2>/dev/null; then
    echo "  ✓ LOOM function imports verified"
else
    echo "  ⚠ Import check failed — ensure LOOM is pip-installed (pip install -e ${LOOM_PROJECT_ROOT})"
fi

echo ""
echo "  Hermes auto-discovery will register the following tools on next restart:"
echo "    loom_recommend  — 決策素材生成（卦→召→評）"
echo "    loom_solidify   — 洞察寫入知識庫"
echo "    loom_find_partners — 三向量模型匹配"
echo "    loom_query      — RAG 知識檢索"
echo "    loom_ingest     — 知識攝入"
echo "    loom_status     — 系統狀態"
echo "    loom_classify   — 嵌入分類"
echo "    loom_loom_close — Conversation 關閉"
echo ""
echo "  To restart Hermes:  systemctl --user restart hermes-agent  (or hermes restart)"
