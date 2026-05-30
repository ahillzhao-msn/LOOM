#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# LOOM + YiCeNet — Hermes Plugin Installer
# Wires LOOM recommend/solidify and YiCeNet predict as native
# Hermes pre/post hooks via the plugin system.
# ──────────────────────────────────────────────────────────────
set -euo pipefail

PLUGIN_NAME="loom-hooks"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
PLUGIN_DIR="$HERMES_HOME/plugins/$PLUGIN_NAME"
VENV_PYTHON="$HERMES_HOME/hermes-agent/venv/bin/python3"

echo "═══ Installing LOOM + YiCeNet plugin ═══"

# ── 1. Create plugin directory ──
mkdir -p "$PLUGIN_DIR"
echo "✓ Plugin dir: $PLUGIN_DIR"

# ── 2. Write plugin.yaml manifest ──
cat > "$PLUGIN_DIR/plugin.yaml" << 'YAML'
name: loom-hooks
version: 1.0.0
description: >
  LOOM knowledge flywheel + YiCeNet hexagram as native Hermes hooks.
  pre_llm_call → loom_recommend (inject context) + yicenet_predict (hexagram baseline)
  post_llm_call → loom_solidify (save insights to vector KB)
  on_session_start → yicenet_predict (establish hexagram baseline)
  on_session_end → loom_solidify (session-level insights)
author: Hermes Agent
hooks:
  - on_session_start
  - pre_llm_call
  - post_llm_call
  - on_session_end
YAML
echo "✓ plugin.yaml"

# ── 3. Write __init__.py ──
cat > "$PLUGIN_DIR/__init__.py" << 'PYEOF'
"""
LOOM + YiCeNet — Hermes built-in hooks.

Transforms LOOM recommend/solidify and YiCeNet predict from
opt-in tool calls into always-on lifecycle hooks.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

logger = logging.getLogger("loom-hooks")

# Add source paths so LOOM and YiCeNet are importable at runtime
_HERMES_HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
_LOOM_SRC = os.path.expanduser("~/LOOM/src")
_YICENET_SRC = os.path.expanduser("~/YiCeNet/src")

for _p in [_LOOM_SRC, _YICENET_SRC]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Lazy imports — only load when hooks fire
_loom_recommend = None
_loom_solidify = None
_yicenet_predict = None


def _get_loom_recommend():
    global _loom_recommend
    if _loom_recommend is None:
        try:
            from loom.tools.hermes_tools import loom_recommend as lr
            _loom_recommend = lr
        except ImportError as e:
            logger.warning("loom_recommend not available: %s", e)
            _loom_recommend = False
    return _loom_recommend if _loom_recommend else None


def _get_loom_solidify():
    global _loom_solidify
    if _loom_solidify is None:
        try:
            from loom.tools.hermes_tools import loom_solidify as ls
            _loom_solidify = ls
        except ImportError as e:
            logger.warning("loom_solidify not available: %s", e)
            _loom_solidify = False
    return _loom_solidify if _loom_solidify else None


def _get_yicenet():
    global _yicenet_predict
    if _yicenet_predict is None:
        try:
            from yicenet.hermes_tool import yicenet_predict as yp
            _yicenet_predict = yp
        except ImportError as e:
            logger.warning("yicenet_predict not available: %s", e)
            _yicenet_predict = False
    return _yicenet_predict if _yicenet_predict else None


# ── Hook Handlers ─────────────────────────────────────────


def on_session_start(**kw: Any) -> None:
    """Establish hexagram baseline at session start."""
    session_id = kw.get("session_id", "?")
    platform = kw.get("platform", "?")
    logger.debug("loom-hooks: session_start sid=%s platform=%s", session_id, platform)

    # YiCeNet baseline
    yp = _get_yicenet()
    if yp:
        try:
            result = yp(f"Session start: {platform}", temperature=0.1, deterministic=True)
            logger.debug("yicenet baseline: %s", str(result)[:120])
        except Exception as e:
            logger.debug("yicenet baseline skipped: %s", e)


def pre_llm_call(**kw: Any) -> dict | str | None:
    """Inject LOOM context + YiCeNet hexagram before every LLM call.

    Returns a dict with ``context`` when knowledge is found,
    or None when there's nothing to inject (silent — no overhead).
    """
    user_message = kw.get("user_message", "")
    session_id = kw.get("session_id", "")
    is_first = kw.get("is_first_turn", False)

    if not user_message or not user_message.strip():
        return None

    context_parts = []

    # 1. LOOM knowledge recall
    lr = _get_loom_recommend()
    if lr:
        try:
            rec = lr(user_message)
            import json
            data = json.loads(rec) if isinstance(rec, str) else rec
            inject = data.get("inject_text") or data.get("context") or ""
            if inject and len(inject) > 10:
                context_parts.append(inject)
        except Exception as e:
            logger.debug("loom_recommend skipped: %s", e)

    # 2. YiCeNet hexagram on first turn only (expensive)
    if is_first:
        yp = _get_yicenet()
        if yp:
            try:
                hx = yp(user_message[:200], temperature=0.1)
                if hx and len(hx) > 10:
                    context_parts.append(f"[Hexagram insight]\n{hx[:300]}")
            except Exception as e:
                logger.debug("yicenet predict skipped: %s", e)

    if not context_parts:
        return None

    combined = "\n\n".join(context_parts)
    return {"context": combined}


def post_llm_call(**kw: Any) -> None:
    """Solidify insights after each LLM turn."""
    ls = _get_loom_solidify()
    if not ls:
        return

    user_message = kw.get("user_message", "")
    assistant_response = kw.get("assistant_response", "")
    session_id = kw.get("session_id", "")

    if not assistant_response or not assistant_response.strip():
        return

    # Build a concise insight: what was asked + key response points
    insight = f"Q: {user_message[:300]}"
    insight += f"\nA: {assistant_response[:500]}"

    try:
        ls(insight=insight, domain="conversation", source="loom_hooks")
    except Exception as e:
        logger.debug("loom_solidify skipped: %s", e)


def on_session_end(**kw: Any) -> None:
    """Solidify session wrap-up."""
    ls = _get_loom_solidify()
    if not ls:
        return
    session_id = kw.get("session_id", "?")
    try:
        ls(insight=f"Session ended: {session_id}", domain="meta", source="loom_hooks_session")
    except Exception as e:
        logger.debug("session_end solidify skipped: %s", e)


# ── Plugin Registration ──────────────────────────────────


def register(ctx) -> None:
    """Register all lifecycle hooks."""
    ctx.register_hook("on_session_start", on_session_start)
    ctx.register_hook("pre_llm_call", pre_llm_call)
    ctx.register_hook("post_llm_call", post_llm_call)
    ctx.register_hook("on_session_end", on_session_end)
    logger.info("loom-hooks: registered 4 lifecycle hooks")
PYEOF
echo "✓ __init__.py"

# ── 4. Enable plugin ──
echo ""
echo "── Enabling plugin ──"
if command -v hermes &>/dev/null; then
    hermes plugins enable "$PLUGIN_NAME" 2>&1 || {
        echo "⚠ 'hermes plugins enable' not available. Manually add:"
        echo "  plugins:"
        echo "    enabled: [$PLUGIN_NAME]"
        echo "to ~/.hermes/config.yaml"
        # Fallback: patch config.yaml directly
        CONFIG="$HERMES_HOME/config.yaml"
        python3 -c "
import yaml
with open('$CONFIG') as f:
    cfg = yaml.safe_load(f)
plugins = cfg.get('plugins', {})
enabled = plugins.get('enabled', [])
if '$PLUGIN_NAME' not in enabled:
    enabled.append('$PLUGIN_NAME')
    plugins['enabled'] = enabled
    cfg['plugins'] = plugins
    with open('$CONFIG', 'w') as f:
        yaml.dump(cfg, f, default_flow_style=False)
    print('✓ Patched config.yaml')
"
    }
else:
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
