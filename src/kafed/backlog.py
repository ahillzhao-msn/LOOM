"""KAFED Knowledge — Backlog 跨 session 待辦管理。

規範 API + 持久化格式。
scripts/backlog.py 和 knowledge/ingest.py 均由此模塊提供後端。

格式（v2）：
  {
    "version": 2,
    "items": [{
      "id": "backlog_001",
      "title": "...",
      "description": "",
      "status": "pending",
      "priority_score": 0.7,
      "value_weight": 0.7,
      "temporal_priority": 0.5,
      "created_at": "ISO datetime"
    }],
    "formula": {},
    "history": []
  }
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from kafed.config import get_config

logger = logging.getLogger("kafed.knowledge.backlog")

# ── 常量 ──────────────────────────────────────────

DEFAULT_FORMULA = "value_weight * 0.6 + temporal_priority * 0.4"
AUTO_PROMOTE_DAYS = 14


# ── 內部操作 ─────────────────────────────────────

def _backlog_path() -> Path:
    return get_config().backlog_data


def _load() -> dict:
    bp = _backlog_path()
    if bp.exists():
        try:
            return json.loads(bp.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"version": 2, "items": [], "formula": {}, "categories": {}, "history": []}


def _save(bl: dict) -> None:
    bl["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    bp = _backlog_path()
    bp.parent.mkdir(parents=True, exist_ok=True)
    bp.write_text(json.dumps(bl, ensure_ascii=False, indent=2))


def _next_id(bl: dict) -> str:
    nums = [int(i.split("_")[1]) for i in
            (item.get("id", "") for item in bl.get("items", []))
            if i.startswith("backlog_")]
    return f"backlog_{max(nums) + 1:03d}" if nums else "backlog_001"


def _reprioritize(bl: dict) -> dict:
    """重新計算所有 priority_score。"""
    formula = bl.get("formula", {})
    w1 = 0.6
    w2 = 0.4
    now = datetime.now(timezone.utc)

    for item in bl.get("items", []):
        v = item.get("value_weight", 0.5)
        t = item.get("temporal_priority", 0.5)

        # 自動提升：擱置逾期的待辦逐漸提升時效權重
        created_raw = item.get("created_at")
        if created_raw and item.get("status") == "pending":
            try:
                days = (now - datetime.fromisoformat(created_raw)).days
                if days > AUTO_PROMOTE_DAYS:
                    t = min(1.0, t + (days - AUTO_PROMOTE_DAYS) * 0.02)
            except (ValueError, TypeError):
                pass

        item["priority_score"] = round(v * w1 + t * w2, 3)

    return bl


# ── 公開 API ─────────────────────────────────────


def push(title: str, value: float = 0.7, description: str = "") -> bool:
    """推入一條待辦。

    Args:
        title: 簡短標題
        value: 價值權重（0-1），影響 priority_score
        description: 可選詳細描述

    Returns:
        True（總是成功，符合日誌式承諾）
    """
    bl = _load()
    item = {
        "id": _next_id(bl),
        "title": title[:80],
        "description": description[:200],
        "status": "pending",
        "priority_score": round(value * 0.6 + 0.5 * 0.4, 3),
        "value_weight": value,
        "temporal_priority": 0.5,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    bl.setdefault("items", []).append(item)
    bl = _reprioritize(bl)
    _save(bl)
    return True


def check() -> list[dict]:
    """返回所有 pending 待辦，按 priority_score 降序。"""
    bl = _load()
    bl = _reprioritize(bl)
    items = [i for i in bl.get("items", []) if i.get("status") == "pending"]
    items.sort(key=lambda x: x.get("priority_score", 0), reverse=True)
    return items


def pop() -> Optional[dict]:
    """取出（標記 in_progress）最高優先 pending 項。

    Returns:
        最高優先項 dict，或 None（佇列空）
    """
    pending = check()
    if not pending:
        return None
    top = pending[0]
    bl = _load()
    for item in bl.get("items", []):
        if item.get("id") == top["id"]:
            item["status"] = "in_progress"
            item["updated_at"] = datetime.now(timezone.utc).isoformat()
            break
    _save(bl)
    return top


def mark_done(item_id: str) -> bool:
    """標記待辦完成。"""
    bl = _load()
    for item in bl.get("items", []):
        if item.get("id") == item_id:
            item["status"] = "done"
            item["updated_at"] = datetime.now(timezone.utc).isoformat()
            bl.setdefault("history", []).append({
                "action": "completed",
                "id": item_id,
                "title": item.get("title", ""),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            _save(bl)
            return True
    return False


def reprioritize() -> int:
    """強制重算所有 priority_score。

    Returns:
        更新的待辦數量
    """
    bl = _load()
    bl = _reprioritize(bl)
    _save(bl)
    return len(bl.get("items", []))


def count() -> int:
    """返回當前 pending 數量。"""
    return len(check())
