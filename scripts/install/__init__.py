"""
LOOM + YiCeNet — Hermes lifecycle hooks.

Transforms LOOM recommend/solidify and YiCeNet predict from
opt-in tool calls into always-on lifecycle hooks.

四鉤子設計（詳見 docs/hooks-evolution.md）:
  pre_llm_call  → loom_recommend (注入 context)
  pre_tool_call → 工具查重（僅觀察不阻斷）
  post_tool_call → 嚴格判定新工具 → 僅新工具時 solidify
  post_llm_call  → 輕量記錄（不 heavy solidify）
  post_api_request → token 累積
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

logging.getLogger("loom-hooks").setLevel(logging.INFO)
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

# Per-session token usage accumulator
_session_usage: dict[str, dict[str, float]] = {}

# pre_tool_call → post_tool_call 狀態橋接
# key: tool_call_id, value: {path, existed_before}
_pre_tool_state: dict[str, dict] = {}

# ── Helpers ──────────────────────────────────────────────


def _yicenet_feedback(session_id: str, response_chars: int,
                      input_chars: int, n_turns: int,
                      model: str, platform: str,
                      success: bool = True) -> None:
    """Write reward signal to YiCeNet's training buffer file.

    Closes the RL flywheel loop: post_llm_call → reward →
    flywheel buffer → next training tick.
    """
    if not _YICENET_BUFFER:
        return

    usage = _session_usage.pop(session_id, {})
    token_cost = usage.get("total_tokens", 0) or int(response_chars * 0.25)
    token_efficiency = usage.get("efficiency", 0)
    if not token_efficiency:
        total = input_chars + response_chars + 1
        token_efficiency = response_chars / total if total > 0 else 0.5

    # Base satisfaction on success
    satisfaction = 0.6 if success else 0.2
    # Boost by token efficiency
    satisfaction = min(1.0, satisfaction + token_efficiency * 0.3)

    sample = {
        "user_text": f"[loom-hooks] sid={session_id[:12]}",
        "producer": "loom-hooks",
        "conversation_id": session_id,
        "hexagram_evolution": [],
        "timestamp": time.time(),
        "token_cost": int(token_cost),
        "token_efficiency": round(token_efficiency, 4),
        "continued": False,
        "corrected": False,
        "completed": n_turns > 0,
        "praised": False,
        "abandoned": False,
        "satisfaction": round(satisfaction, 4),
    }

    try:
        os.makedirs(os.path.dirname(_YICENET_BUFFER), exist_ok=True)
        with open(_YICENET_BUFFER, "a") as f:
            f.write(json.dumps(sample) + "\n")
    except Exception as e:
        logger.debug("yicenet_feedback write failed: %s", e)


def _record_api_usage(session_id: str, usage_data: dict | None) -> None:
    """Accumulate per-session token usage from post_api_request."""
    if not session_id or not usage_data:
        return
    if session_id not in _session_usage:
        _session_usage[session_id] = {
            "total_tokens": 0, "api_calls": 0,
            "total_input": 0, "total_output": 0,
        }
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
    """Check if path is under Hermes tools/ directory."""
    resolved = os.path.abspath(os.path.expanduser(path))
    tools_dir = os.path.abspath(os.path.join(
        os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")),
        "hermes-agent", "tools"
    ))
    return resolved.startswith(tools_dir)


def _has_registry_register(content: str) -> bool:
    """Check if content registers as a Hermes tool."""
    return "registry.register(" in content


def _is_draft_content(content: str) -> bool:
    """Check if content is marked as draft/WIP."""
    markers = ["Draft", "WIP", "TODO", "FIXME", "HACK", "TEMP"]
    return any(m in content for m in markers)


# ── Hook Handlers ─────────────────────────────────────────


def on_session_start(**kw: Any) -> None:
    """Establish hexagram baseline at session start."""
    session_id = kw.get("session_id", "?")
    platform = kw.get("platform", "?")
    logger.debug("loom-hooks: session_start sid=%s platform=%s", session_id, platform)
    # baseline already handled by SOUL.md → loom_recommend()
    # no YiCeNet call here — LOOM's recommend() absorbs it internally


def pre_llm_call(**kw: Any) -> dict | str | None:
    """Inject LOOM context (含 YiCeNet 卦象在內的完整決策素材).

    LOOM 的 recommend() 內部已調用 YiCeNet 做卦步驟，
    所以不應在這裡額外調用 yicenet_predict。

    Returns dict with ``context`` when found, or None (silent).
    """
    user_message = kw.get("user_message", "")
    if not user_message or not user_message.strip():
        return None

    lr = _get_loom_recommend()
    if not lr:
        return None

    try:
        rec = lr(user_message)
        data = json.loads(rec) if isinstance(rec, str) else rec
        inject = data.get("inject_text") or data.get("context") or ""
        if inject and len(inject) > 10:
            return {"context": inject}
    except Exception as e:
        logger.debug("loom_recommend skipped: %s", e)

    return None


def pre_tool_call(**kw: Any) -> None:
    """觀察：工具調用前的路徑檢查。

    初期只觀察不阻斷——記錄工具目標路徑，供 post_tool_call 判斷。

    設計原則（hooks-evolution.md §Hook3）:
      - 僅對 write_file/patch 觸發
      - 記錄路徑是否存在（判斷是否新工具）
      - 不返回 block，不阻斷工具執行
    """
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
        # 解析 > 和 >> 後的目標路徑
        for marker in (">>", ">"):
            if marker in cmd:
                parts = cmd.split(marker, 1)
                if len(parts) > 1:
                    path = parts[1].strip().split()[0] if parts[1].strip() else ""
                    # Strip quotes
                    path = path.strip("'\"")
                    break
    else:
        # 非代碼工具，不記錄
        return

    if not path or not _is_tool_path(path):
        return

    existed = os.path.exists(os.path.expanduser(path))
    _pre_tool_state[tool_call_id] = {
        "path": path,
        "existed_before": existed,
    }


def post_tool_call(**kw: Any) -> None:
    """學習：工具執行後的處理。

    最嚴格抑噪——僅在「新工具被創建」時 solidify：

    六條件全滿足才固化（hooks-evolution.md §Hook4）:
    ① 工具名是 write_file/patch/terminal
    ② 目標在 tools/ 下
    ③ 內容含 registry.register(
    ④ 該文件之前不存在
    ⑤ 執行成功
    ⑥ 非草稿內容

    不滿足任一條件 → 跳過，0ms 開銷。
    """
    tool_name = kw.get("tool_name", "")
    args = kw.get("args", {})
    result = kw.get("result", "")
    tool_call_id = kw.get("tool_call_id", "")
    duration_ms = kw.get("duration_ms", 0)

    # 條件①：工具名過濾
    if tool_name not in ("write_file", "patch", "terminal"):
        return

    # 從 pre_tool_state 取出之前記錄的路徑
    state = _pre_tool_state.pop(tool_call_id, None)
    if not state:
        return
    path = state["path"]

    # 條件④：必須是新文件
    if state["existed_before"]:
        logger.debug("post_tool_call skip (existing): %s", path)
        return

    # 條件⑤：執行成功
    success = True
    if isinstance(result, str):
        try:
            res = json.loads(result)
            if isinstance(res, dict) and "error" in res:
                success = False
        except (json.JSONDecodeError, TypeError):
            pass  # non-JSON result = success (terminal output)

    if not success:
        logger.debug("post_tool_call skip (failed): %s", path)
        return

    # 提取內容檢查（條件③⑥）
    content = ""

    if tool_name == "write_file":
        content = args.get("content", "")
    elif tool_name == "patch":
        content = args.get("new_string", "")
    elif tool_name == "terminal":
        # terminal 命令不檢查內容——假設指向 tools/ 就有意
        content = "registry.register()"  # 繞過內容檢查
        # 但保留條件⑥：不繞過草稿檢查
        cmd = args.get("command", "")
        if _is_draft_content(cmd):
            logger.debug("post_tool_call skip (draft cmd): %s", path)
            return

    # 條件③：含 registry.register(
    if not _has_registry_register(content):
        logger.debug("post_tool_call skip (no register): %s", path)
        return

    # 條件⑥：非草稿
    if _is_draft_content(content):
        logger.debug("post_tool_call skip (draft): %s", path)
        return

    # 六條件全滿足 → solidify
    ls = _get_loom_solidify()
    if ls:
        insight = (
            f"New Hermes tool: {os.path.basename(path)}\n"
            f"Path: {path}\n"
            f"Created via: {tool_name} ({duration_ms}ms)\n"
            f"Content preview: {content[:200]}"
        )
        try:
            ls(insight=insight, domain="toolkit", source="loom_hooks_tool")
            logger.info("loom-hooks: solidified new tool %s", path)
        except Exception as e:
            logger.debug("loom_solidify failed: %s", e)


def post_llm_call(**kw: Any) -> None:
    """輕量記錄（Option B——不 heavy solidify）.

    Plugin 層只寫 YiCeNet flywheel reward signal。
    Heavy solidify 保留由 Agent 在 SOUL.md 指令下手動調用。
    """
    user_message = kw.get("user_message", "")
    assistant_response = kw.get("assistant_response", "")
    session_id = kw.get("session_id", "")
    model = kw.get("model", "unknown")
    platform = kw.get("platform", "")
    history = kw.get("conversation_history", [])
    n_turns = sum(1 for m in history if isinstance(m, dict) and m.get("role") == "assistant")

    if not assistant_response or not assistant_response.strip():
        return

    # 只寫 flywheel reward，不 solidify 到 KAFED
    _yicenet_feedback(
        session_id=session_id,
        response_chars=len(assistant_response),
        input_chars=len(user_message or ""),
        n_turns=n_turns,
        model=model,
        platform=platform,
    )


def post_api_request(**kw: Any) -> None:
    """Capture token usage for accurate YiCeNet reward computation."""
    usage = kw.get("usage")
    if usage and isinstance(usage, dict):
        _record_api_usage(kw.get("session_id", ""), usage)


def on_session_end(**kw: Any) -> None:
    """Session wrap-up — lightweight log only."""
    session_id = kw.get("session_id", "?")
    logger.debug("loom-hooks: session_end sid=%s", session_id)


# ── Plugin Registration ──────────────────────────────────


def register(ctx) -> None:
    """Register all lifecycle hooks."""
    ctx.register_hook("on_session_start", on_session_start)
    ctx.register_hook("pre_llm_call", pre_llm_call)
    ctx.register_hook("pre_tool_call", pre_tool_call)
    ctx.register_hook("post_tool_call", post_tool_call)
    ctx.register_hook("post_llm_call", post_llm_call)
    ctx.register_hook("post_api_request", post_api_request)
    ctx.register_hook("on_session_end", on_session_end)
    logger.info("loom-hooks: registered 7 lifecycle hooks (4-hook architecture)")
