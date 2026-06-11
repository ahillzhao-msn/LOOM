#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# LOOM — pip install into Hermes venv (via uv)
#
# Install strategy:
#   1. Detect Hermes venv
#   2. Download LOOM wheel from latest GitHub release
#   3. Install wheel into Hermes venv via uv (no source code needed)
#   4. Install/update loom-hooks plugin
#   5. Run bootstrap if first install
# ──────────────────────────────────────────────────────────────
set -euo pipefail

REPO="ahillzhao-msn/LOOM"
PLUGIN_NAME="loom-hooks"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "═══ Installing LOOM into Hermes venv ═══"

# ── 1. Detect Hermes venv python ──
VENV_PY=""
if command -v hermes &>/dev/null; then
    VENV_PY="$(hermes -z 'which python' 2>/dev/null || true)"
fi
if [ -z "$VENV_PY" ]; then
    # Fallback: common paths
    for cand in \
        "$HERMES_HOME/hermes-agent/venv/bin/python" \
        "$HERMES_HOME/.venv/bin/python" \
        "$HERMES_HOME/venv/bin/python"; do
        if [ -x "$cand" ]; then
            VENV_PY="$cand"
            break
        fi
    done
fi
if [ -z "$VENV_PY" ]; then
    echo "✗ Hermes venv not found. Install Hermes first."
    echo "  Or manually: uv pip install --python <hermes-python> loom @ <wheel-url>"
    exit 1
fi
echo "✓ Hermes python: $VENV_PY"

# Ensure uv is available
UV="$(command -v uv || command -v pip3 || echo '')"
if [ -z "$UV" ]; then
    echo "✗ uv not found. Install with: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi
echo "✓ uv: $UV"

# ── 2. Determine version (from tag or latest) ──
VERSION="${1:-latest}"
if [ "$VERSION" = "latest" ]; then
    echo "  → Fetching latest release..."
    LATEST="$(
        curl -sL "https://api.github.com/repos/$REPO/releases/latest" \
        | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'])"
    )"
    VERSION="$LATEST"
fi
echo "  Version: $VERSION"

# ── 3. Download + install wheel into Hermes venv ──
WHEEL_URL="https://github.com/$REPO/releases/download/$VERSION"
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

echo "  → Downloading wheel..."
cd "$TMPDIR"
curl -sL "$WHEEL_URL" -o release.json 2>/dev/null || true
# Find the .whl URL from the release
WHEEL_FILE="$(
    curl -sL "https://api.github.com/repos/$REPO/releases/tags/$VERSION" \
    | python3 -c "
import sys, json
data = json.load(sys.stdin)
for a in data.get('assets', []):
    if a['name'].endswith('.whl'):
        print(a['name'])
        break
"
)"
if [ -z "$WHEEL_FILE" ]; then
    echo "✗ No wheel found in release $VERSION"
    echo "  Run uv build first, then push the tag."
    exit 1
fi

echo "  → Downloading $WHEEL_FILE..."
curl -sL "$WHEEL_URL/$WHEEL_FILE" -o "$TMPDIR/$WHEEL_FILE"

echo "  → Installing into Hermes venv..."
uv pip install --python "$VENV_PY" "$TMPDIR/$WHEEL_FILE"

# Verify import
echo "  → Verifying..."
"$VENV_PY" -c "from loom import __version__; print(f'✓ LOOM v{__version__} installed')"

# ── 4. Install/update loom-hooks plugin ──
echo ""
echo "── Installing Hermes plugin ──"
PLUGIN_DIR="$HERMES_HOME/plugins/$PLUGIN_NAME"
mkdir -p "$PLUGIN_DIR"

# Write plugin.yaml
cat > "$PLUGIN_DIR/plugin.yaml" << 'YAML'
name: loom-hooks
version: 2.0.0
description: >
  LOOM knowledge flywheel as native Hermes hooks. 四鉤子架構:
    pre_llm_call -> loom_recommend (inject context)
    pre_tool_call -> tool path inspection (observe only)
    post_tool_call -> strict new-tool detection -> selective solidify
    post_llm_call -> lightweight yicenet feedback (no heavy solidify)
    post_api_request -> accumulate token usage
  Design doc: docs/hooks-evolution.md
author: Hermes Agent
hooks:
  - on_session_start
  - pre_llm_call
  - pre_tool_call
  - post_tool_call
  - post_llm_call
  - post_api_request
  - on_session_end
YAML

# Write __init__.py (from template — uses installed package, not source path)
cat > "$PLUGIN_DIR/__init__.py" << 'PYEOF'
"""LOOM + YiCeNet -- Hermes lifecycle hooks.

Installed via "uv pip install loom" into Hermes venv.
All imports resolve from the installed package (no source-path hacks).
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

logging.getLogger("loom-hooks").setLevel(logging.INFO)
logger = logging.getLogger("loom-hooks")

# Lazy imports -- resolved from installed package
_loom_recommend = None
_loom_solidify = None


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


# YiCeNet flywheel buffer path
_YICENET_BUFFER = str(Path.home() / "YiCeNet" / "data" / "flywheel_buffer.jsonl")
_session_usage: dict[str, dict[str, float]] = {}
_pre_tool_state: dict[str, dict] = {}


def _yicenet_feedback(session_id: str, response_chars: int,
                      input_chars: int, n_turns: int,
                      model: str, platform: str,
                      success: bool = True) -> None:
    if not _YICENET_BUFFER:
        return
    usage = _session_usage.pop(session_id, {})
    token_cost = usage.get("total_tokens", 0) or int(response_chars * 0.25)
    token_efficiency = usage.get("efficiency", 0)
    if not token_efficiency:
        total = input_chars + response_chars + 1
        token_efficiency = response_chars / total if total > 0 else 0.5
    satisfaction = min(1.0, (0.6 if success else 0.2) + token_efficiency * 0.3)
    sample = {
        "user_text": f"[loom-hooks] sid={session_id[:12]}",
        "producer": "loom-hooks",
        "conversation_id": session_id,
        "hexagram_evolution": [],
        "timestamp": time.time(),
        "token_cost": int(token_cost),
        "token_efficiency": round(token_efficiency, 4),
        "continued": False, "corrected": False,
        "completed": n_turns > 0, "praised": False, "abandoned": False,
        "satisfaction": round(satisfaction, 4),
    }
    try:
        os.makedirs(os.path.dirname(_YICENET_BUFFER), exist_ok=True)
        with open(_YICENET_BUFFER, "a") as f:
            f.write(json.dumps(sample) + "\n")
    except Exception as e:
        logger.debug("yicenet_feedback write failed: %s", e)


def _record_api_usage(session_id: str, usage_data: dict | None) -> None:
    if not session_id or not usage_data:
        return
    if session_id not in _session_usage:
        _session_usage[session_id] = {"total_tokens": 0, "api_calls": 0, "total_input": 0, "total_output": 0}
    acc = _session_usage[session_id]
    acc["total_tokens"] += usage_data.get("total_tokens", 0) or 0
    acc["api_calls"] += 1
    in_tok = usage_data.get("input_tokens", 0) or usage_data.get("prompt_tokens", 0) or 0
    out_tok = usage_data.get("output_tokens", 0) or usage_data.get("completion_tokens", 0) or 0
    acc["total_input"] += in_tok
    acc["total_output"] += out_tok
    total = acc["total_input"] + acc["total_output"]
    acc["efficiency"] = acc["total_output"] / total if total > 0 else 0.5


def _is_tool_path(path: str) -> bool:
    resolved = os.path.abspath(os.path.expanduser(path))
    tools_dir = os.path.abspath(os.path.join(
        os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")),
        "hermes-agent", "tools"
    ))
    return resolved.startswith(tools_dir)


def _has_registry_register(content: str) -> bool:
    return "registry.register(" in content


def _is_draft_content(content: str) -> bool:
    markers = ["Draft", "WIP", "TODO", "FIXME", "HACK", "TEMP"]
    return any(m in content for m in markers)


# YiCeNet attend (cross-attention prescription)
_yicenet_attend = None


def _get_yicenet_attend():
    global _yicenet_attend
    if _yicenet_attend is None:
        try:
            from yicenet import YiCeNetEngine
            engine = YiCeNetEngine()
            _yicenet_attend = engine.attend
        except ImportError as e:
            logger.warning("yicenet_attend not available: %s", e)
            _yicenet_attend = False
    return _yicenet_attend if _yicenet_attend else None


_session_turn_counter: dict[str, int] = {}


def _next_turn_id(session_id: str) -> int:
    tid = _session_turn_counter.get(session_id, 0)
    _session_turn_counter[session_id] = tid + 1
    return tid


def _build_compressed_history(conv_history: list, prescription: dict,
                              max_retain_chars: int = 600,
                              max_summary_chars: int = 120) -> str:
    retain = set(prescription.get("retain_turns", []))
    summarize = set(prescription.get("summarize_turns", []))
    if not retain and not summarize:
        return ""
    user_turns = []
    for msg in conv_history:
        if isinstance(msg, dict) and msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, list):
                text_parts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
                content = " ".join(text_parts)
            user_turns.append(content[:500])
    lines = []
    max_turn_id = max((list(retain) + list(summarize) + [-1]))
    for tid in range(max_turn_id + 1):
        if tid >= len(user_turns):
            break
        msg = user_turns[tid].strip()
        if not msg:
            continue
        if tid in retain:
            truncated = msg[:max_retain_chars]
            if len(msg) > max_retain_chars:
                truncated += "\u2026"
            lines.append(f"[{tid}] {truncated}")
        elif tid in summarize:
            truncated = msg[:max_summary_chars]
            if len(msg) > max_summary_chars:
                truncated += "\u2026"
            lines.append(f"[{tid}:摘要] {truncated}")
    if not lines:
        return ""
    insight = prescription.get("key_insight", "")
    header = f"\u3008歷史摘要 | {prescription.get('mode', '?')} | {insight}\u3009"
    return header + "\n" + "\n".join(lines)


_embedder = None


def _get_embedding(text: str) -> list[float] | None:
    global _embedder
    if _embedder is None:
        try:
            from sentence_transformers import SentenceTransformer
            _embedder = SentenceTransformer('BAAI/bge-small-en-v1.5')
        except ImportError as e:
            logger.debug("bge-small not available: %s", e)
            _embedder = False
    if not _embedder:
        return None
    try:
        emb = _embedder.encode(text[:512])
        return emb.tolist()
    except Exception as e:
        logger.debug("embedding failed: %s", e)
        return None


# ── Hook Handlers ──

def on_session_start(**kw: Any) -> None:
    session_id = kw.get("session_id", "?")
    platform = kw.get("platform", "?")
    logger.debug("loom-hooks: session_start sid=%s platform=%s", session_id, platform)


def pre_llm_call(**kw: Any) -> dict | str | None:
    user_message = kw.get("user_message", "")
    session_id = kw.get("session_id", "")
    if not user_message or not user_message.strip():
        return None
    loom_inject = ""
    lr = _get_loom_recommend()
    if lr:
        try:
            rec = lr(user_message)
            data = json.loads(rec) if isinstance(rec, str) else rec
            loom_inject = data.get("inject_text") or data.get("context") or ""
        except Exception as e:
            logger.debug("loom_recommend skipped: %s", e)
    rx = {}
    attend_fn = _get_yicenet_attend()
    if attend_fn and session_id:
        try:
            turn_id = _next_turn_id(session_id)
            import numpy as np
            emb_list = _get_embedding(user_message)
            emb = np.array(emb_list, dtype=np.float32) if emb_list else None
            result = attend_fn(text=user_message, session_id=session_id, turn_id=turn_id,
                               turn_summary=user_message[:80], embedding=emb)
            rx = result.get("context_prescription", {})
        except Exception as e:
            logger.debug("yicenet_attend skipped: %s", e)
    history_summary = ""
    if rx and rx.get("mode") != "full":
        conv_hist = kw.get("conversation_history", [])
        history_summary = _build_compressed_history(conv_hist, rx)
    parts = []
    if loom_inject and len(loom_inject) > 10:
        parts.append(loom_inject)
    if history_summary:
        parts.append(history_summary)
    if parts:
        return {"context": "\n\n".join(parts)}
    return None


def pre_tool_call(**kw: Any) -> None:
    tool_name = kw.get("tool_name", "")
    args = kw.get("args", {})
    tool_call_id = kw.get("tool_call_id", "")
    if not tool_call_id:
        return
    path = ""
    if tool_name == "write_file":
        path = args.get("path", "")
    elif tool_name == "patch":
        path = args.get("path", "")
    elif tool_name == "terminal":
        cmd = args.get("command", "")
        for marker in (">>", ">"):
            if marker in cmd:
                parts = cmd.split(marker, 1)
                if len(parts) > 1:
                    path = parts[1].strip().split()[0] if parts[1].strip() else ""
                    path = path.strip("'\"")
                    break
    else:
        return
    if not path or not _is_tool_path(path):
        return
    existed = os.path.exists(os.path.expanduser(path))
    _pre_tool_state[tool_call_id] = {"path": path, "existed_before": existed}


def post_tool_call(**kw: Any) -> None:
    tool_name = kw.get("tool_name", "")
    args = kw.get("args", {})
    result = kw.get("result", "")
    tool_call_id = kw.get("tool_call_id", "")
    duration_ms = kw.get("duration_ms", 0)
    if tool_name not in ("write_file", "patch", "terminal"):
        return
    state = _pre_tool_state.pop(tool_call_id, None)
    if not state:
        return
    path = state["path"]
    if state["existed_before"]:
        logger.debug("post_tool_call skip (existing): %s", path)
        return
    success = True
    if isinstance(result, str):
        try:
            res = json.loads(result)
            if isinstance(res, dict) and "error" in res:
                success = False
        except (json.JSONDecodeError, TypeError):
            pass
    if not success:
        logger.debug("post_tool_call skip (failed): %s", path)
        return
    content = ""
    if tool_name == "write_file":
        content = args.get("content", "")
    elif tool_name == "patch":
        content = args.get("new_string", "")
    elif tool_name == "terminal":
        content = "registry.register()"
        cmd = args.get("command", "")
        if _is_draft_content(cmd):
            logger.debug("post_tool_call skip (draft cmd): %s", path)
            return
    if not _has_registry_register(content):
        logger.debug("post_tool_call skip (no register): %s", path)
        return
    if _is_draft_content(content):
        logger.debug("post_tool_call skip (draft): %s", path)
        return
    ls = _get_loom_solidify()
    if ls:
        insight = (f"New Hermes tool: {os.path.basename(path)}\n"
                   f"Path: {path}\nCreated via: {tool_name} ({duration_ms}ms)\n"
                   f"Content preview: {content[:200]}")
        ls(insight, domain="TOOLS", source="hermes_plugin")


def post_api_request(**kw: Any) -> None:
    usage = kw.get("usage")
    if usage and isinstance(usage, dict):
        _record_api_usage(kw.get("session_id", ""), usage)


def post_llm_call(**kw: Any) -> None:
    user_message = kw.get("user_message", "")
    assistant_response = kw.get("assistant_response", "")
    session_id = kw.get("session_id", "")
    model = kw.get("model", "unknown")
    platform = kw.get("platform", "")
    history = kw.get("conversation_history", [])
    n_turns = sum(1 for m in history if isinstance(m, dict) and m.get("role") == "assistant")
    if not assistant_response or not assistant_response.strip():
        return
    _yicenet_feedback(session_id, len(assistant_response), len(user_message or ""),
                      n_turns, model, platform)


def on_session_end(**kw: Any) -> None:
    session_id = kw.get("session_id", "?")
    logger.debug("loom session ended: %s", session_id[:12])


def register(ctx) -> None:
    ctx.register_hook("on_session_start", on_session_start)
    ctx.register_hook("pre_llm_call", pre_llm_call)
    ctx.register_hook("pre_tool_call", pre_tool_call)
    ctx.register_hook("post_tool_call", post_tool_call)
    ctx.register_hook("post_api_request", post_api_request)
    ctx.register_hook("post_llm_call", post_llm_call)
    ctx.register_hook("on_session_end", on_session_end)
    logger.info("loom-hooks: registered 7 hooks")
PYEOF

echo "✓ Plugin written to $PLUGIN_DIR"

# ── 5. Enable plugin ──
echo ""
echo "── Enabling plugin ──"
if command -v hermes &>/dev/null; then
    hermes plugins enable "$PLUGIN_NAME" 2>&1 || echo "⚠ hermes plugins enable failed — enable manually in config.yaml"
else
    echo "⚠ hermes CLI not found — manually enable in config.yaml"
fi

# ── 6. Run bootstrap (first-time setup) ──
echo ""
echo "── Bootstrap ──"
"$VENV_PY" -c "
from loom.install.bootstrap import main as bootstrap
print('✓ loom-bootstrap available (run manually with: loom-bootstrap)')
" 2>/dev/null || echo "  (bootstrap module not yet deployed — run later)"

echo ""
echo "═══ LOOM install complete ═══"
echo "  Package: installed in Hermes venv"
echo "  Plugin:  $PLUGIN_DIR"
echo "  To activate: restart Hermes"
echo "  To verify:   hermes plugins list | grep loom"
echo "  To remove:   hermes plugins disable $PLUGIN_NAME && rm -rf $PLUGIN_DIR"
