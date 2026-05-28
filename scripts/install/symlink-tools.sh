#!/bin/bash
# KAFED Hermes Tool Symlink Installer
# 將 KAFED 工具註冊到 Hermes 的 tools/ 目錄

set -e

KAFED_TOOL_SRC="$(cd "$(dirname "$0")/../.." && pwd)/src/kafed/tools/hermes_tools.py"
HERMES_TOOLS_DIR="${HOME}/.hermes/hermes-agent/tools"

if [ ! -f "$KAFED_TOOL_SRC" ]; then
    echo "ERROR: KAFED tools not found at: $KAFED_TOOL_SRC"
    exit 1
fi

mkdir -p "$HERMES_TOOLS_DIR"

# 移除舊 symlink（若存在）
rm -f "${HERMES_TOOLS_DIR}/kafed_tool.py"

# 建立新 symlink
ln -sf "$KAFED_TOOL_SRC" "${HERMES_TOOLS_DIR}/kafed_tool.py"

echo "✓ KAFED tools symlinked:"
echo "  ${HERMES_TOOLS_DIR}/kafed_tool.py → ${KAFED_TOOL_SRC}"

# 驗證
if python3 -c "from kafed.tools.hermes_tools import kafed_recommend" 2>/dev/null; then
    echo "✓ Import verified: kafed_recommend() available"
else
    echo "⚠ Import check failed — ensure KAFED is pip-installed (pip install -e ~/KAFED)"
fi
