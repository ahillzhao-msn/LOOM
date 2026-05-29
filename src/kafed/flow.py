"""
FlowVisualizer — KAFED 內部流程可視化。

用 Context Manager 模式注入關鍵步驟執行介面，自動捕獲步驟與結果。
兩模式：compact（實時箭頭鏈到 stderr）、detailed（累積後 Agent 用於回應頭部）。

格式邏輯封裝在 FlowEntry.compact_detail() 中，步驟代碼只提供原始數據。

用法:
    with flow_step("D", "問", "5W1H") as ctx:
        w5 = _step_5w1h(input)
        ctx.data = {"what": w5.what, "where": w5.where}  # 原始數據
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Optional


# ── 全局開關 ──────────────────────────────────
_ENABLED: bool | None = None
_MODE: str = "compact"  # "compact" | "detailed"


def flow_enabled() -> bool:
    global _ENABLED
    if _ENABLED is not None:
        return _ENABLED
    env = os.getenv("KAFED_FLOW")
    if env is not None:
        return env.lower() in ("1", "true", "yes", "on")
    return sys.stderr.isatty()


def set_flow_enabled(val: bool):
    global _ENABLED
    _ENABLED = val


def set_flow_mode(mode: str):
    """切換模式：'compact' 或 'detailed'。"""
    global _MODE
    assert mode in ("compact", "detailed"), f"unknown mode: {mode}"
    _MODE = mode


# ── 會話（累積器）───────────────────────────────

@dataclass
class FlowEntry:
    module: str       # D, K, A, F, E
    action: str       # 問/卦/召/評/固, or 找/派/讀/寫...
    detail: str = ""  # 步驟標籤（顯示用 fallback）
    result: str = ""  # 執行結果摘要（detailed 模式用）
    data: dict = field(default_factory=dict)  # 結構化原始數據（formatter 用）

    def compact_detail(self) -> str:
        """根據 action 類型生成精簡摘要（≤20 字符）。"""
        d = self.data or {}

        if self.action == "問":
            # 5W1H 關鍵詞，≤10 字符
            for key in ("what", "where", "who", "how"):
                val = d.get(key, "")
                if val:
                    # 取最長不超過 10 字
                    return val[:10]
            return self.detail[:10]

        if self.action == "卦":
            # 排版格式由 YiCeNet 自持
            compact = d.get("compact", "")
            if compact:
                return compact[:20]
            return self.detail[:10] if self.detail else "?"

        if self.action == "召":
            # 各源計數: M(2) W(1) S(2) R(3) K(1)
            parts = []
            for key, label in [("memory", "M"), ("wiki", "W"),
                               ("skills", "S"), ("recall", "R"), ("rag", "K")]:
                cnt = d.get(key, 0)
                if cnt:
                    parts.append(f"{label}[{cnt}]")
            return " ".join(parts) if parts else self.detail[:15]

        if self.action == "評":
            # Tier + Score
            tier = d.get("tier", "")
            score = d.get("score", "")
            parts = []
            if tier:
                parts.append(f"T{tier}")
            if score:
                parts.append(f"S{score}")
            return " ".join(parts) if parts else self.result[:15]

        if self.action == "固":
            domain = d.get("domain", "")
            chunks = d.get("chunks", "")
            parts = []
            if domain:
                parts.append(domain[:10])
            if chunks:
                parts.append(f"{chunks}c")
            return " ".join(parts) if parts else self.result[:15]

        # 未知 action：fallback 到 detail
        return self.detail[:15]

    def compact(self) -> str:
        """完整 compact 表示：D問(精簡摘要)"""
        det = self.compact_detail()
        return f"{self.module}{self.action}({det})" if det else f"{self.module}{self.action}"


_entries: list[FlowEntry] = []
_TITLE: str = "Flow"


def flow_reset(title: str = "Flow"):
    """每輪開始時清空並設標題。"""
    global _TITLE
    _entries.clear()
    _TITLE = title


def _render(end: str = ""):
    """將累積鏈渲染到 stderr。"""
    if not flow_enabled():
        return
    parts = [e.compact() for e in _entries]
    line = " -> ".join(parts)
    if end:
        line += f" -> {end}"
    sys.stderr.write(f"[ {_TITLE} ]  {line}\n")
    sys.stderr.flush()


# ── Context Manager ────────────────────────────

@contextmanager
def flow_step(module: str, action: str, detail: str = ""):
    """包裹一個關鍵步驟，自動累加 + 渲染。

    用法:
        with flow_step("D", "問", "5W1H") as ctx:
            w5 = _step_5w1h(input)
            ctx.data = {"what": w5.what, "where": w5.where}  # formatter 用
            ctx.result = "4 維度"                             # detailed 用
    """
    entry = FlowEntry(module=module, action=action, detail=detail)
    _entries.append(entry)
    try:
        yield entry
    except Exception as e:
        entry.result = f"✗ {e}"
        raise
    finally:
        _render()


def flow_mark(module: str, action: str, detail: str = ""):
    """記錄非 KAFED 步驟（開發除錯用），不包裹程式碼。"""
    _entries.append(FlowEntry(module=module, action=action, detail=detail))
    _render()


# ── 查詢 ───────────────────────────────────────

def flow_entries() -> list[FlowEntry]:
    """返回當前會話的流程條目（供 detailed 模式用）。"""
    return list(_entries)


def flow_chain_text(mode: str = "compact") -> str:
    """生成流程鏈文字（供 Agent 嵌入回應頭部）。"""
    parts = [e.compact() for e in _entries]
    if mode == "compact":
        return " -> ".join(parts)
    lines = []
    for i, e in enumerate(_entries):
        result_suffix = f"  → {e.result}" if e.result else ""
        lines.append(f"{i+1}. {e.compact()}{result_suffix}")
    return "\n".join(lines)


# ── 向後相容（舊版場景模板，保留但不推薦） ─────

_W = 54


def _sep(text: str = "") -> str:
    w = max(_W - len(text), 2)
    return f"{'─' * w}"


def chain(
    title: str,
    stations: list[tuple[str, str, str]],
    end: str = "",
    enabled: Optional[bool] = None,
):
    """舊版公交站牌顯示（保留向後相容）。"""
    if not _should_show(enabled):
        return
    lines: list[str] = []
    n = len(stations)
    lines.append(f"  🚏 {title} {_sep()}")
    for i, (icon, name, detail) in enumerate(stations):
        label = f"{icon} {name}" if icon else name
        detail_str = f"  ── {detail}" if detail else ""
        is_last = i == n - 1
        if is_last and not end:
            lines.append(f"  └─ {label}{detail_str}")
        else:
            lines.append(f"  ├─ {label}{detail_str}")
    if end:
        lines.append(f"  └─ {end}")
    lines.append(f"  {_sep()}")
    sys.stderr.write("\n".join(lines) + "\n")
    sys.stderr.flush()


def hop(icon: str, name: str, detail: str = "", enabled: Optional[bool] = None):
    """舊版單步站點（保留向後相容）。"""
    if not _should_show(enabled):
        return
    pfx = f"{icon} " if icon else ""
    tag = f"  ── {detail}" if detail else ""
    sys.stderr.write(f"  🚏 {pfx}{name}{tag}\n")
    sys.stderr.flush()


def stop(msg: str, icon: str = "✅", enabled: Optional[bool] = None):
    """終點。"""
    if not _should_show(enabled):
        return
    sys.stderr.write(f"  └─ {icon} {msg}\n\n")
    sys.stderr.flush()


def divider(title: str = "", enabled: Optional[bool] = None):
    """分隔線。"""
    if not _should_show(enabled):
        return
    t = f" {title} " if title else ""
    sys.stderr.write(f"  {_sep(t)}\n")
    sys.stderr.flush()


def _should_show(enabled: Optional[bool]) -> bool:
    if enabled is not None:
        return enabled
    return flow_enabled()
