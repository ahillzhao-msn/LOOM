"""
FlowVisualizer — 公交站牌式信息流可視化。

CLI 上展示操作鏈條，像公交路線圖。
全局開關：set_flow_enabled(True/False) 或 KAFED_FLOW=0 環境變量。

用法:
    from kafed.client import flow

    flow.chain("記憶寫入", [
        ("🔍", "洞察", "設計審視教訓"),
        ("🏷️", "類型判斷", "架構決策"),
        ("📍", "分流", "wiki/concepts/"),
    ], end="✅ 固化完成")
"""

from __future__ import annotations

import os
import sys
from typing import Optional

# ── 全局開關 ──────────────────────────────────
_ENABLED: bool | None = None  # None = 自動


def flow_enabled() -> bool:
    global _ENABLED
    if _ENABLED is not None:
        return _ENABLED
    # 環境變量 > stderr 是否 tty
    env = os.getenv("KAFED_FLOW")
    if env is not None:
        return env.lower() in ("1", "true", "yes", "on")
    return sys.stderr.isatty()


def set_flow_enabled(val: bool):
    global _ENABLED
    _ENABLED = val


# ── 渲染 ──────────────────────────────────────

_W = 54  # 路線圖寬度


def _sep(text: str = "") -> str:
    w = max(_W - len(text), 2)
    return f"{'─' * w}"


def chain(
    title: str,
    stations: list[tuple[str, str, str]],
    end: str = "",
    enabled: Optional[bool] = None,
):
    """公交站牌式信息流展示。

    stations: [(icon, name, detail), ...]
    end: 終點標語（可選）
    enabled: 覆蓋全局開關
    """
    if not _should_show(enabled):
        return

    lines: list[str] = []
    n = len(stations)

    # 標題行
    lines.append(f"  🚏 {title} {_sep()}")

    for i, (icon, name, detail) in enumerate(stations):
        label = f"{icon} {name}" if icon else name
        detail_str = f"  ── {detail}" if detail else ""
        is_last = i == n - 1

        if is_last and not end:
            lines.append(f"  └─ {label}{detail_str}")
        else:
            lines.append(f"  ├─ {label}{detail_str}")

    # 終點
    if end:
        lines.append(f"  └─ {end}")

    # 底線
    lines.append(f"  {_sep()}")

    sys.stderr.write("\n".join(lines) + "\n")
    sys.stderr.flush()


def hop(icon: str, name: str, detail: str = "", enabled: Optional[bool] = None):
    """單步站點（非鏈式，隨到隨打）。"""
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


# ── 場景模板 ──────────────────────────────────


def memory_flow(insight: str, target: str, path: str = ""):
    chain("記憶寫入", [
        ("🔍", "洞察", insight),
        ("🏷️", "類型", target),
        ("📍", "分流", path or target),
    ], end="✅ 固化完成")


def kafed_query_flow(query: str, domain: str, top_k: int, results_count: int):
    chain("KAFED 查詢", [
        ("🔍", "query", query),
        ("📊", "檢索", f"domain={domain} top_k={top_k}"),
        ("📎", "返回", f"{results_count} 條結果"),
    ], end="✅ 查詢完成")


def ingest_flow(filename: str, domain: str, chunks: int, elapsed: float):
    chain("知識攝入", [
        ("📄", "讀取", filename),
        ("✂️", "分塊", f"{chunks} chunks"),
        ("🏷️", "分類", f"→ {domain}"),
        ("💾", "入庫", f"{elapsed:.1f}s"),
    ], end="✅ 攝入完成")


def pipeline_flow(steps: list[tuple[str, str, str]]):
    chain("處理管線", steps, end="✅ 完成")
