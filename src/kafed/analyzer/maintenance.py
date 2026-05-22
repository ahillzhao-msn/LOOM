"""
KAFED Analyzer — 維護排程器。

處理背景維護任務：
- 記憶壓縮（Memory pruning）
- Wiki 同步（KAFED → wiki/concepts/）
- 飛輪 E3/E5 觸發
- 知識過期清理
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class MaintenanceReport:
    """維護報告。"""
    task: str
    status: str            # completed / skipped / failed
    details: str = ""
    
    def describe(self) -> str:
        icons = {"completed": "✅", "skipped": "⏭️", "failed": "❌"}
        return f"{icons.get(self.status, '❓')} {self.task}: {self.details}"


class MaintenanceScheduler:
    """維護排程器。
    
    處理所有非分析性的背景維護任務。
    
    歸屬層：
    - Memory 壓縮 → Analyzer（因為是背景維護）
    - Wiki 同步 → Knowledge（屬於知識輸出）
    - E3/E5 飛輪 → Knowledge（屬於知識自我維護）
    - 知識清理 → Knowledge
    
    此模塊只排程和觸發，具體邏輯在各層實現。
    """
    
    @staticmethod
    def check_e3_repack_needed(event_state: dict) -> bool:
        """檢查是否需要 E3 重打包（域增長 > 30% 且 >= 200 條目）。"""
        packed = event_state.get("packed_domains", {})
        chunk_totals = event_state.get("chunk_totals", {})
        
        for domain, count in chunk_totals.items():
            if domain not in packed:
                if count >= 200:
                    return True
            else:
                packed_info = packed[domain]
                packed_count = packed_info.get("count_at_pack", 0)
                growth = (count - packed_count) / max(packed_count, 1)
                if growth > 0.3 and count >= 200:
                    return True
        
        return False
    
    @staticmethod
    def check_e5_stale(event_state: dict) -> list[str]:
        """檢查 E5 過期域（90 天無查詢）。"""
        last_query = event_state.get("last_query", {})
        now = datetime.now(timezone.utc)
        stale = []
        
        for domain, ts in last_query.items():
            if ts is None:
                continue
            try:
                last_dt = datetime.fromisoformat(ts)
                days = (now - last_dt).days
                if days >= 90:
                    stale.append(domain)
            except (ValueError, TypeError):
                pass
        
        return stale
    
    @staticmethod
    def estimate_memory_usage(memory_entries: int, avg_size: int = 200) -> str:
        """估算 Memory 使用。"""
        total_bytes = memory_entries * avg_size
        if total_bytes < 1024:
            return f"{total_bytes} B"
        elif total_bytes < 1024 * 1024:
            return f"{total_bytes / 1024:.1f} KB"
        else:
            return f"{total_bytes / 1024 / 1024:.1f} MB"
    
    @staticmethod
    def memory_compression_check(memory_entries: int, max_target: int = 20000) -> MaintenanceReport:
        """檢查是否需要記憶壓縮。"""
        usage = MaintenanceScheduler.estimate_memory_usage(memory_entries)
        if memory_entries > max_target:
            return MaintenanceReport(
                task="memory_compression",
                status="completed",
                details=f"Memory {memory_entries} 條 ({usage})，超過目標 {max_target}，需壓縮",
            )
        return MaintenanceReport(
            task="memory_compression",
            status="skipped",
            details=f"Memory {memory_entries} 條 ({usage})，低於閾值",
        )
