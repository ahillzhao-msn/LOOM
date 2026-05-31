"""
梭子 (Shuttle) — Loom 的信息探针。

在 Conversation → Session → Turn 的经纬之间穿梭，
收集关键信息并提供多种优雅展示模式。

核心抽象：
  Step — 原子步骤（CxSyTz-N 全局唯一 ID）
  @step() 装饰器 — 包裹函数，自动计时/注册/异常处理
"""

from __future__ import annotations

import functools
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .models import TurnRecord, SessionRecord, ConversationRecord


# ── 全局开关 ──

def shuttle_enabled() -> bool:
    env = os.getenv("LOOM_SHUTTLE", "1")
    return env.lower() in ("1", "true", "yes", "on")


# ── 数据模型 ──

@dataclass
class Step:
    """原子步骤。CxSyTz-N 格式保证整个 LOOM 生命周期内唯一。

    id:       "C2S1T4-0" — Conversation 2, Session 1, Turn 4, Step 0
    module:   "D" (Director), "K" (Knowledge), "A" (Analyzer)
    action:   "问", "卦", "召", "评", "固"
    detail:   "5W1H", "䷏豫", "K[5]W[2]", "T1 S1.00"
    status:   "ok" | "error"
    duration: 秒
    """
    id: str
    module: str
    action: str
    detail: str
    status: str
    duration: float
    timestamp: float = field(default_factory=time.time)


# ── 装饰器 ──

_step_counter: int = 0


def step(module: str, action: str) -> Callable:
    """装饰器：包裹步骤函数，自动执行：

    1. 注册到 Shuttle._steps（ID 自动生成）
    2. 计时（duration）
    3. try/except — 异常时 status="error" 仍生成 Step

    被装饰函数应返回 (result, detail_str) 二元组。
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.time()
            try:
                result = func(*args, **kwargs)
                duration = time.time() - start
                if isinstance(result, tuple) and len(result) == 2:
                    detail = str(result[1])
                    result = result[0]
                else:
                    detail = action
                Shuttle.register_step(module=module, action=action,
                                      detail=detail, status="ok",
                                      duration=duration)
                return result
            except Exception as e:
                duration = time.time() - start
                Shuttle.register_step(module=module, action=action,
                                      detail=f"✗ {e}", status="error",
                                      duration=duration)
                raise
        return wrapper
    return decorator


# ── Shuttle 核心类 ──

class Shuttle:
    """梭子 — 多种织法（展示模式）。所有方法都是 @staticmethod。"""

    _steps: list[Step] = []

    # ── 步骤注册 ──

    @classmethod
    def reset_steps(cls) -> None:
        """每轮开始时调用。清空步骤列表。"""
        cls._steps = []

    @classmethod
    def register_step(cls, step_id: str = "", module: str = "", action: str = "",
                       detail: str = "", status: str = "ok",
                       duration: float = 0.0) -> Step:
        """注册一个步骤到内部列表。

        当 step_id 为空时自动从 manager.status 生成 CxSyTz-N 格式 ID。
        当 step_id 已提供 CxSyTz-open/close 等格式时直接使用。
        """
        if not step_id:
            from loom.manager.client import manager as _m
            s = _m.status()
            c = s.get("conv_seq", 0)
            ses = s.get("session_count", 0)
            t_n = s.get("active_session_turns", 0)
            global _step_counter
            _step_counter += 1
            step_id = f"C{c}S{ses}T{t_n}-{_step_counter}"
        step = Step(id=step_id, module=module, action=action,
                    detail=detail, status=status, duration=duration)
        cls._steps.append(step)
        return step

    @classmethod
    def steps_snapshot(cls) -> list[Step]:
        """返回步骤列表的浅拷贝（供外部只读访问）。"""
        return list(cls._steps)

    # ── 织法 1：流程链（每轮即时）──

    @staticmethod
    def flow_chain(steps: list[Step] | list[str], end: str = "") -> str:
        """从 Step 对象或字符串列表生成流程链文字。

        兼容两种输入：
        - list[Step] — 使用 module/action/detail 渲染
        - list[str] — 直接拼接（向后兼容）
        """
        parts = []
        for s in steps:
            if isinstance(s, str):
                parts.append(s)
            else:
                label = f"{s.module}{s.action}({s.detail})" if s.detail else f"{s.module}{s.action}"
                parts.append(label)
        line = " -> ".join(parts)
        if end:
            line += f" -> {end}"
        return line

    @staticmethod
    def emit_flow(title: str = "LOOM", end: str = "") -> None:
        """输出当前所有步骤的流程链到 stderr。"""
        if not shuttle_enabled():
            return
        line = Shuttle.flow_chain(Shuttle._steps, end)
        sys.stderr.write(f"[ {title} ]  {line}\n")
        sys.stderr.flush()

    # ── 织法 2：卦链足迹（跨轮次）──

    @staticmethod
    def hexagram_trail(hexagram_ids: list[int]) -> str:
        """卦象演化足迹。"""
        if not hexagram_ids:
            return ""
        try:
            from yicenet.display import hexagram_symbol as sym
            _has_yicenet = True
        except (ImportError, ModuleNotFoundError):
            _has_yicenet = False
        ids = [h for h in hexagram_ids if h > 0]
        if not ids:
            return "—"

        parts = []
        for hid in ids:
            if _has_yicenet:
                symbol = sym(hid + 1)
                parts.append(symbol or f"#{hid}")
            else:
                parts.append(f"#{hid}")

        if len(ids) >= 3:
            diffs = [abs(ids[i] - ids[i-1]) for i in range(1, len(ids))]
            avg_sum = sum(diffs) / len(diffs)
            if avg_sum <= 1:
                return " → ".join(parts) + " · 稳定"
            if avg_sum <= 5:
                return " → ".join(parts) + " · 漂移"
            return " → ".join(parts) + " · 跳跃"

        return " → ".join(parts)

    # ── 织法 3：Session 锦缎 ──

    @staticmethod
    def session_tapestry(session: SessionRecord) -> str:
        """单一 session 的完整面貌。"""
        if not session or not session.turns:
            return "(empty session)"
        ss = session.summarize()
        lines = [
            f"Session {ss['session_id'][:8]}",
            f"  {ss['turns']} 轮 · {ss['total_tokens']} tokens · {ss['solidifies']} 次固化",
        ]
        trail = Shuttle.hexagram_trail(ss['hexagram_evolution'])
        if trail:
            lines.append(f"  卦: {trail}")
        keys = session.key_turns(2)
        if keys:
            for k in keys:
                markers = []
                if k.had_correction:
                    markers.append("修正")
                if k.had_affirmation:
                    markers.append("肯定")
                if markers:
                    lines.append(f"  ⚡ {k.query[:20]:20s} {' '.join(markers)}")
        return "\n".join(lines)

    # ── 织法 4：Conversation 全貌 ──

    @staticmethod
    def conversation_tapestry(conv: ConversationRecord) -> str:
        """整场对话的织锦。"""
        if not conv:
            return "(no conversation)"
        reward = conv.reward_for_flywheel()
        lines = [
            f"Conversation {conv.conversation_id[:8]}",
            f"  {reward['n_sessions']} sessions · {reward['n_turns']} 轮",
        ]
        trail = Shuttle.hexagram_trail(reward['hexagram_evolution'])
        if trail:
            lines.append(f"  卦: {trail}")
        lines.append(f"  效率: {reward['token_efficiency']:.4f} token/轮")
        lines.append(f"  修正率: {reward['correction_rate']:.0%}")
        lines.append(f"  固化: {reward['total_solidifies']} 次")
        patterns = reward.get('session_patterns', [])
        if patterns:
            pattern_str = " | ".join(
                f"S{i+1}={p}" for i, p in enumerate(patterns)
            )
            lines.append(f"  session 模式: {pattern_str}")
        return "\n".join(lines)

    # ── 织法 5：Session 级别渲染（边界触发）──

    @staticmethod
    def session_render(session: SessionRecord, event: str = "start") -> None:
        """Session 边界时输出全景摘要。"""
        if not shuttle_enabled() or not session:
            return
        if event == "close":
            Shuttle.display(Shuttle.session_tapestry(session))

    # ── 织法 7：卦链脉冲（每轮固态后自适应展示）──

    @staticmethod
    def hexagram_pulse() -> None:
        """自适应卦链脉冲。由 solidify() 每轮末尾触发。

        展现策略：
        - 0-1 个卦 → 不展示（已在流程链中）
        - 2-3 个卦 → 完整展示
        - 4+ 个卦 → 仅末 3 个 + "(共N)"
        - 模式跳跃 → 完整展示并标模式变化
        """
        if not shuttle_enabled():
            return
        try:
            from loom.manager.client import manager as _m
            session = _m.active_session
            if not session or not session.turns:
                return
            ids = session.summarize().get("hexagram_evolution", [])
            ids = [h for h in ids if h > 0]
            if len(ids) <= 1:
                return  # 已在 emit_flow 中

            from loom.hexagram import hexagram_display, hexagram_judgment

            # 符号+名的卦链
            try:
                from yicenet.display import hexagram_symbol as _sym
                def _hx_sym(hid): return _sym(hid + 1)
            except (ImportError, ModuleNotFoundError):
                _hx_sym = lambda hid: f"#{hid}"

            pattern = ""
            judgement = ""
            if len(ids) >= 3:
                diffs = [abs(ids[i] - ids[i-1]) for i in range(1, len(ids))]
                avg_s = sum(diffs) / len(diffs)
                if avg_s <= 1:
                    pattern = "稳定"; judgement = "节奏平稳"
                elif avg_s <= 5:
                    pattern = "漂移"; judgement = "主题流变"
                else:
                    pattern = "跳跃"; judgement = "方向转换"

            named_parts = [_hx_sym(h) + (hexagram_display(h) or "") for h in ids]
            named_chain = " → ".join(named_parts)
            # 综合判辞：从序列卦辞中提取关键字信号
            _sig = {"亨": 0, "吉": 0, "利": 0, "凶": 0, "厉": 0, "咎": 0, "悔": 0, "吝": 0}
            for _hid in ids:
                _j = hexagram_judgment(_hid)
                for _kw in _sig:
                    if _kw in _j:
                        _sig[_kw] += 1
            _pos = _sig["亨"] + _sig["吉"] + _sig["利"]
            _neg = _sig["凶"] + _sig["厉"] + _sig["咎"] + _sig["悔"] + _sig["吝"]
            if _pos > _neg:
                _combined = "亨通"
            elif _neg > _pos:
                _combined = "警慎"
            else:
                _combined = "中平"
            if pattern:
                _combined += f"·{pattern}"
            if len(ids) <= 3:
                Shuttle.display(f"[ 易策 ]  {named_chain} · {_combined}")
            else:
                tail_named = " → ".join(named_parts[-3:])
                Shuttle.display(f"[ 易策 ]  {tail_named} · (共{len(ids)}卦) · {_combined}")
        except Exception:
            pass  # 优雅降级

    # ── 织法 8：策略调整（基于卦链模式）──

    @staticmethod
    def hexagram_strategy() -> dict:
        """返回基于卦链模式的自适应策略建议。

        Returns:
            {"mode": "concise" | "thorough" | "reset",
             "pattern": "稳定" | "漂移" | "跳跃" | "",
             "reason": str}
        """
        try:
            from loom.manager.client import manager as _m
            session = _m.active_session
            if not session or not session.turns:
                return {"mode": "", "pattern": "", "reason": ""}
            ids = session.summarize().get("hexagram_evolution", [])
            ids = [h for h in ids if h > 0]
            if len(ids) < 2:
                return {"mode": "concise", "pattern": "", "reason": "开局阶段"}

            diffs = [abs(ids[i] - ids[i-1]) for i in range(1, len(ids))]
            avg_s = sum(diffs) / len(diffs)
            last_diff = diffs[-1] if diffs else 0

            if avg_s <= 1 and last_diff <= 1:
                return {"mode": "concise", "pattern": "稳定",
                        "reason": f"连续{len(ids)}卦稳定，可加速"}
            if avg_s <= 5:
                return {"mode": "thorough", "pattern": "漂移",
                        "reason": f"主题持续演化中({len(ids)}卦)，保持上下文深度"}
            # 跳跃
            if len(ids) <= 3:
                return {"mode": "thorough", "pattern": "跳跃",
                        "reason": f"新方向({len(ids)}卦)，需深挖理解"}
            return {"mode": "reset", "pattern": "跳跃",
                    "reason": f"大幅跳跃({len(ids)}卦)，考虑重置上下文焦点"}
        except Exception:
            return {"mode": "", "pattern": "", "reason": ""}

    @staticmethod
    def conversation_render(conv, event: str = "close") -> None:
        """Conversation 边界时输出跨 session 摘要。"""
        if not shuttle_enabled() or not conv:
            return
        if event == "close":
            Shuttle.display(Shuttle.conversation_tapestry(conv))

    # ── 通用输出 ──

    @staticmethod
    def display(text: str) -> None:
        """输出到 stderr（不干扰 Agent 回应）。"""
        if shuttle_enabled():
            sys.stderr.write(text + "\n")
            sys.stderr.flush()
