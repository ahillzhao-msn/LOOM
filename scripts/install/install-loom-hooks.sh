#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# LOOM + YiCeNet — Hermes Plugin Installer
# Wires LOOM recommend/solidify and YiCeNet predict as native
# Hermes pre/post hooks via the plugin system.
#
# Installs from filesystem files (scripts/install/plugin.yaml and
# __init__.py), NOT from inline heredocs — so source and install
# stay in sync automatically.
# ──────────────────────────────────────────────────────────────
set -euo pipefail

PLUGIN_NAME="loom-hooks"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
PLUGIN_DIR="$HERMES_HOME/plugins/$PLUGIN_NAME"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="$HERMES_HOME/hermes-agent/venv/bin/python3"

echo "═══ Installing LOOM + YiCeNet plugin ═══"

# ── 1. Create plugin directory ──
mkdir -p "$PLUGIN_DIR"
echo "✓ Plugin dir: $PLUGIN_DIR"

# ── 2. Write plugin.yaml (from script directory) ──
if [ -f "$SCRIPT_DIR/plugin.yaml" ]; then
    cp "$SCRIPT_DIR/plugin.yaml" "$PLUGIN_DIR/plugin.yaml"
    echo "✓ plugin.yaml"
else
    echo "✗ plugin.yaml not found at $SCRIPT_DIR/plugin.yaml"
    echo "  The plugin.yaml must exist alongside this install script."
    exit 1
fi

# ── 3. Write __init__.py (from script directory) ──
if [ -f "$SCRIPT_DIR/__init__.py" ]; then
    cp "$SCRIPT_DIR/__init__.py" "$PLUGIN_DIR/__init__.py"
    echo "✓ __init__.py"
else
    echo "✗ __init__.py not found at $SCRIPT_DIR/__init__.py"
    echo "  The __init__.py must exist alongside this install script."
    exit 1
fi

# ── 4. Enable plugin ──
echo ""
echo "── Enabling plugin ──"
if command -v hermes &>/dev/null; then
    hermes plugins enable "$PLUGIN_NAME" 2>&1 || {
        echo "⚠ 'hermes plugins enable' not available. Patching config.yaml directly..."
        CONFIG="$HERMES_HOME/config.yaml"
        python3 -c "
import yaml
with open('$CONFIG') as f:
    cfg = yaml.safe_load(f)
plugins = cfg.setdefault('plugins', {})
enabled = plugins.setdefault('enabled', [])
if '$PLUGIN_NAME' not in enabled:
    enabled.append('$PLUGIN_NAME')
with open('$CONFIG', 'w') as f:
    yaml.dump(cfg, f, default_flow_style=False)
print('✓ Patched config.yaml')
"
    }
else
    echo "⚠ hermes CLI not found — skipping enable step"
fi

echo ""
echo "── Verification ──"
echo "Plugin dir: $PLUGIN_DIR"
ls -la "$PLUGIN_DIR/"
echo ""
echo "Config check:"
grep -A 2 "enabled:" "$HERMES_HOME/config.yaml" | head -5
echo ""

# ── 5. Verify imports ──
echo "── Import test ──"
"$VENV_PYTHON" -c "
import sys
sys.path.insert(0, '$HOME/LOOM/src')
sys.path.insert(0, '$HOME/YiCeNet/src')
from loom.tools.hermes_tools import loom_recommend, loom_solidify
print('LOOM:  loom_recommend ✓  loom_solidify ✓')
from yicenet.hermes_tool import yicenet_predict
print('YiCeNet: yicenet_predict ✓')
print('All imports OK — plugin ready.')
" 2>&1

echo ""
echo "═══ Install complete ═══"
echo "To activate: restart Hermes (exit this session, start a new one)"
echo "To verify: hermes plugins list | grep loom-hooks"
echo "To remove:  hermes plugins disable loom-hooks"
echo "              rm -rf ~/.hermes/plugins/loom-hooks"
