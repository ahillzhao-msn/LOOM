"""
KAFED Analyzer — 湧現計算器。

檢測長期數據中的結構性變化：
- Centroid drift（域原型向量漂移）
- Domain shift（領域分佈變化）
- 遺忘曲線觸發（E5 stale）
- 新湧現模式（前所未見的組合）

與 YiCeNet 的接口：
  Emergence calculator 可以：
  1. 餵數據給 YiCeNet 的世界模型（增量學習）
  2. 消費 YiCeNet 的卦象分佈來檢測狀態變化
  3. 相關積累數據與 YiCeNet 的預測結果做交叉驗證
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class DriftReport:
    """漂移檢測報告。"""
    domain: str
    current_count: int
    previous_count: int
    cosine_drift: float           # centroid 餘弦變化量
    is_significant: bool          # drift > 0.05
    timestamp: str = ""
    
    def describe(self) -> str:
        status = "⚠️ 顯著漂移" if self.is_significant else "✅ 穩定"
        return (
            f"[{self.domain}] {status}\n"
            f"  chunks: {self.previous_count} → {self.current_count}\n"
            f"  drift: {self.cosine_drift:.4f}"
        )


@dataclass
class StaleReport:
    """過期檢測報告。"""
    domain: str
    days_since_last_query: int
    is_stale: bool                 # >= 90 天
    chunk_count: int
    
    def describe(self) -> str:
        if self.is_stale:
            return f"🧹 [{self.domain}] 已過期 ({self.days_since_last_query}天無查詢, {self.chunk_count} chunks)"
        return f"[{self.domain}] 未過期 ({self.days_since_last_query}天)"


@dataclass
class EmergenceSignal:
    """湧現信號——前所未見的結構性變化。"""
    signal_type: str               # new_domain_emergence / cross_domain_link / behavior_shift
    description: str
    strength: float                # 0.0 - 1.0
    data: dict = field(default_factory=dict)
    
    def describe(self) -> str:
        return f"🌟 [{self.signal_type}] {self.description} (strength: {self.strength:.2f})"


class EmergenceCalculator:
    """湧現計算器。
    
    檢測長期數據中的結構性變化，產生 EmergenceSignal。
    可與 YiCeNet 的世界模型交叉驗證。
    """
    
    DRIFT_THRESHOLD = 0.05       # E2 觸發閾值
    STALE_DAYS = 90              # E5 過期閾值
    NEW_DOMAIN_MIN_COUNT = 5     # 新域湧現的最小 chunk 數
    
    def __init__(self):
        self.signals: list[EmergenceSignal] = []
    
    def check_centroid_drift(self, current: dict[str, int], previous: dict[str, int]) -> list[DriftReport]:
        """檢測 centroid 漂移（E2 事件）。"""
        reports = []
        all_domains = set(current.keys()) | set(previous.keys())
        
        for domain in all_domains:
            cur_count = current.get(domain, 0)
            prev_count = previous.get(domain, 0)
            
            if prev_count == 0 and cur_count == 0:
                continue
            
            # 簡單漂移估算：數量變化率作為 proxy
            if prev_count > 0:
                drift = abs(cur_count - prev_count) / max(prev_count, 1)
            else:
                drift = 1.0 if cur_count > 0 else 0.0
            
            reports.append(DriftReport(
                domain=domain,
                current_count=cur_count,
                previous_count=prev_count,
                cosine_drift=min(drift, 1.0),
                is_significant=drift > self.DRIFT_THRESHOLD,
            ))
            
            if drift > self.DRIFT_THRESHOLD:
                self.signals.append(EmergenceSignal(
                    signal_type="centroid_drift",
                    description=f"域 {domain} 發生顯著漂移 ({drift:.3f})",
                    strength=min(drift, 1.0),
                    data={"domain": domain, "drift": drift, "counts": (prev_count, cur_count)},
                ))
        
        return reports
    
    def check_stale(self, domain_queries: dict[str, Optional[str]], domain_counts: dict[str, int]) -> list[StaleReport]:
        """檢查過期域（E5 事件）。"""
        from datetime import datetime, timezone
        
        reports = []
        now = datetime.now(timezone.utc)
        
        for domain, last_query_ts in domain_queries.items():
            if last_query_ts is None:
                days = float("inf")
            else:
                try:
                    last_dt = datetime.fromisoformat(last_query_ts)
                    days = (now - last_dt).days
                except (ValueError, TypeError):
                    days = float("inf")
            
            is_stale = days >= self.STALE_DAYS
            reports.append(StaleReport(
                domain=domain,
                days_since_last_query=int(days) if days != float("inf") else 999,
                is_stale=is_stale,
                chunk_count=domain_counts.get(domain, 0),
            ))
            
            if is_stale:
                self.signals.append(EmergenceSignal(
                    signal_type="domain_stale",
                    description=f"域 {domain} 已 {int(days)} 天無查詢，標為 stale",
                    strength=0.6,
                    data={"domain": domain, "days": int(days), "chunks": domain_counts.get(domain, 0)},
                ))
        
        return reports
    
    def check_new_domain(self, current_domains: set[str], previous_domains: set[str],
                         domain_counts: dict[str, int]) -> list[EmergenceSignal]:
        """檢測新域湧現。"""
        new_domains = current_domains - previous_domains
        signals = []
        
        for domain in new_domains:
            count = domain_counts.get(domain, 0)
            if count >= self.NEW_DOMAIN_MIN_COUNT:
                signals.append(EmergenceSignal(
                    signal_type="new_domain_emergence",
                    description=f"新域 \"{domain}\" 湧現 ({count} chunks)",
                    strength=min(count / 100, 1.0),
                    data={"domain": domain, "chunk_count": count},
                ))
        
        return signals
