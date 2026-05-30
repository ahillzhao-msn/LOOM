"""
LOOM + YiCeNet — Hermes built-in hooks.

Transforms LOOM recommend/solidify and YiCeNet predict from
opt-in tool calls into always-on lifecycle hooks.

Also closes YiCeNet's RL flywheel by feeding reward signals
from post_llm_call directly into the training buffer,
replacing the fragile Session DB scan.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

# Quiet down noisy libraries from the plugin's perspective
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


# YiCeNet flywheel buffer path (no import needed — plain file append)
_YICENET_BUFFER = str(Path.home() / "YiCeNet" / "data" / "flywheel_buffer.jsonl")

# Per-session token usage accumulator (for accurate cost from post_api_request)
_session_usage: dict[str, dict[str, float]] = {}

# ── Helpers ──────────────────────────────────────────────


def _yicenet_feedback(session_id: str, response_chars: int,
                      input_chars: int, n_turns: int,
                      model: str, platform: str) -> None:
    """Write reward signal to YiCeNet's training buffer file.

    This closes the RL flywheel loop: post_llm_call → reward →
    flywheel buffer → next training tick.  Replaces the fragile
    Session DB scan that the flywheel used to do.

    The file is consumed by YiCeNet's main flywheel cron
    (every 6h) which reads, splits, and trains on these samples.
    """
    if not _YICENET_BUFFER:
        return

    # Use accumulated per-session token usage if available
    usage = _session_usage.pop(session_id, {})
    token_cost = usage.get("total_tokens", 0) or response_chars * 0.25
    token_efficiency = usage.get("efficiency", 0)
    if not token_efficiency:
        total = input_chars + response_chars + 1
        token_efficiency = response_chars / total if total > 0 else 0.5
    api_calls = int(usage.get("api_calls", n_turns))

    # Model cost multiplier (rough estimate)
    cost_factors = {
        "deepseek-v4-flash": 0.00015,
        "deepseek-v4-pro": 0.0015,
        "deepseek-v3": 0.0009,
    }
    cost_per_char = cost_factors.get(model.split("/")[-1] if "/" in model else model, 0.0003)

    # Build training sample matching flywheel format (see flywheel.py lines 89-103)
    sample = {
        "user_text": f"[loom-hooks] sid={session_id[:12]}",
        "producer": "loom-hooks",
        "conversation_id": session_id,
        "hexagram_evolution": [],
        "timestamp": time.time(),
        "token_cost": int(token_cost),
        "token_efficiency": round(token_efficiency, 4),
        "continued": False,       # will be set by post_api_request / session_end
        "corrected": False,       # proxy: requires user behavior analysis
        "completed": n_turns > 0,
        "praised": False,
        "abandoned": False,
        "satisfaction": round(
            min(1.0, token_efficiency * 1.5)  # proxy: efficient = satisfying
            * (1.0 - min(0.3, cost_per_char * 100)),  # expensive = less satisfying
            4
        ),
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
    """Solidify insights + send reward signal to YiCeNet flywheel."""
    ls = _get_loom_solidify()
    user_message = kw.get("user_message", "")
    assistant_response = kw.get("assistant_response", "")
    session_id = kw.get("session_id", "")
    model = kw.get("model", "unknown")
    platform = kw.get("platform", "")
    history = kw.get("conversation_history", [])
    n_turns = sum(1 for m in history if isinstance(m, dict) and m.get("role") == "assistant")

    # 1. LOOM solidify
    if ls and assistant_response and assistant_response.strip():
        insight = f"Q: {user_message[:300]}\nA: {assistant_response[:500]}"
        try:
            ls(insight=insight, domain="conversation", source="loom_hooks")
        except Exception as e:
            logger.debug("loom_solidify skipped: %s", e)

    # 2. YiCeNet feedback (closes the RL flywheel)
    _yicenet_feedback(
        session_id=session_id,
        response_chars=len(assistant_response or ""),
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
    ctx.register_hook("post_api_request", post_api_request)
    ctx.register_hook("on_session_end", on_session_end)
    logger.info("loom-hooks: registered 5 lifecycle hooks (yicenet feedback active)")
