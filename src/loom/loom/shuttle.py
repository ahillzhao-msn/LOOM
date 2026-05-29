"""
梭子 (Shuttle) — Loom 的資訊探針。

在 Conversation → Session → Turn 的經緯之間穿梭，
收集關鍵資訊並提供多種優雅展示模式。

取代 LOOM flow.py 的 FlowVisualizer——不再局限於每輪流程鏈，
而是跨層級、跨輪次的一體化可視化。
"""

from __future__ import annotations

import os
import sys
from typing import Optional

from .models import TurnRecord, SessionRecord, ConversationRecord


# ── 全局開關 ──

def shuttle_enabled() -> bool:
    env = os.getenv("LOOM_SHUTTLE", "1")
    return env.lower() in ("1", "true", "yes", "on")


# ── 核心展示函數 ──

class Shuttle:
    """梭子 — 多種織法（展示模式）。所有方法都是 @staticmethod。"""

    # ── 織法 1：流程鏈（每輪即時）──

    @staticmethod
    def flow_chain(steps: list[str], end: str = "") -> str:
        """當輪流程節點鏈。取代舊 compact 模式。

        輸入: ["D問", "D卦(YiCeNet)", "D召(LOOM)", "D評(EVAL)"]
        輸出: D問 -> D卦(YiCeNet) -> D召(LOOM) -> D評(EVAL)
        """
        line = " -> ".join(steps)
        if end:
            line += f" -> {end}"
        return line

    @staticmethod
    def emit_flow(steps: list[str], title: str = "Flow", end: str = ""):
        """輸出流程鏈到 stderr。"""
        if not shuttle_enabled():
            return
        line = Shuttle.flow_chain(steps, end)
        sys.stderr.write(f"[ {title} ]  {line}\n")
        sys.stderr.flush()

    # ── 織法 2：卦鏈足跡（跨輪次）──

    @staticmethod
    def hexagram_trail(hexagram_ids: list[int]) -> str:
        """卦象演化足跡。

        輸入: [47, 10, 10, 54]
        輸出: ䷮ → ䷉ · ䷉ → ䷲  (附模式標記)
        """
        if not hexagram_ids:
            return ""
        try:
            from yicenet.display import hexagram_symbol as sym
            _has_yicenet = True
        except (ImportError, ModuleNotFoundError):
            _has_yicenet = False
        # 過濾 0（無卦）
        ids = [h for h in hexagram_ids if h > 0]
        if not ids:
            return "—"

        parts = []
        for i, hid in enumerate(ids):
            if _has_yicenet:
                symbol = sym(hid + 1)
                parts.append(symbol or f"#{hid}")
            else:
                parts.append(f"#{hid}")

        # 標記模式
        if len(ids) >= 3:
            diffs = [abs(ids[i] - ids[i-1]) for i in range(1, len(ids))]
            avg = sum(diffs) / len(diffs)
            if avg <= 1:
                return " → ".join(parts) + " · 穩定"
            if avg <= 5:
                return " → ".join(parts) + " · 漂移"
            return " → ".join(parts) + " · 跳躍"

        return " → ".join(parts)

    # ── 織法 3：Session 錦緞 ──

    @staticmethod
    def session_tapestry(session: SessionRecord) -> str:
        """單一 session 的完整面貌。"""
        if not session or not session.turns:
            return "(empty session)"

        ss = session.summarize()
        lines = [
            f"Session {ss['session_id'][:8]}",
            f"  {ss['turns']} 輪 · {ss['total_tokens']} tokens · {ss['solidifies']} 次固化",
        ]

        # 卦鏈
        trail = Shuttle.hexagram_trail(ss['hexagram_evolution'])
        if trail:
            lines.append(f"  卦: {trail}")

        # 關鍵輪次
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

    # ── 織法 4：Conversation 全貌 ──

    @staticmethod
    def conversation_tapestry(conv: ConversationRecord) -> str:
        """整場對話的織錦。"""
        if not conv:
            return "(no conversation)"

        reward = conv.reward_for_flywheel()
        lines = [
            f"📜 Conversation {conv.conversation_id[:8]}",
            f"  {reward['n_sessions']} sessions · {reward['n_turns']} 輪",
        ]

        # 跨 session 卦演化
        trail = Shuttle.hexagram_trail(reward['hexagram_evolution'])
        if trail:
            lines.append(f"  卦: {trail}")

        # 效率
        lines.append(f"  效率: {reward['token_efficiency']:.4f} token/輪")
        lines.append(f"  修正率: {reward['correction_rate']:.0%}")
        lines.append(f"  固化: {reward['total_solidifies']} 次")

        # 各 session 模式
        patterns = reward.get('session_patterns', [])
        if patterns:
            pattern_str = " | ".join(
                f"S{i+1}={p}" for i, p in enumerate(patterns)
            )
            lines.append(f"  session: {pattern_str}")

        return "\n".join(lines)

    # ── 通用輸出 ──

    @staticmethod
    def display(text: str):
        """輸出到 stderr（不干擾 Agent 回應）。"""
        if shuttle_enabled():
            sys.stderr.write(text + "\n")
            sys.stderr.flush()
