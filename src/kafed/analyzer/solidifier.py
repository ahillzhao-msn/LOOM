"""KAFED Analyzer — 固化引擎。

將 Agent 每輪洞察寫入 KM，觸發飛輪學習閉環。
從舊 entry.solidify() 提取，移除 backlog 目標（改用 Hermes 原生）。
"""

from __future__ import annotations

import logging
from typing import Optional

from kafed.knowledge.ingest import ingest as _km_ingest

logger = logging.getLogger("kafed.analyzer.solidifier")


def solidify(insight: str, domain: str = "GENERAL",
             source: str = "agent_turn", title: str = "") -> dict:
    """將本輪洞察寫入 KAFED 知識庫。

    Args:
        insight: 洞察內容（教訓、發現、模式）
        domain: 域標籤（默認 GENERAL）
        source: 來源標識
        title: 可選標題

    Returns:
        {"status": str, "chunks": int, "detail": str}
    """
    result = _km_ingest(
        text=insight,
        target="kafed",
        domain=domain,
        source=source,
        title=title,
    )
    logger.info("solidify: domain=%s status=%s chunks=%s",
                domain, result.get("status"), result.get("entries", 0))
    return result


def session_end_audit(director_intent: str = "",
                      hexagram_id: int = 0,
                      pipeline_taken: str = "",
                      steps: Optional[list] = None,
                      task_results: Optional[list] = None,
                      solidified: Optional[list] = None,
                      outcome_quality: float = 0.5) -> dict:
    """Session 結束後非同步稽查。

    對比意圖 vs 結果，觸發 KM 修正和飛輪事件。
    """
    from kafed.analyzer.audit import AuditEngine, AuditInput

    inp = AuditInput(
        director_intent=director_intent,
        hexagram_id=hexagram_id,
        pipeline_taken=pipeline_taken,
        steps=steps or [],
        task_results=task_results or [],
        solidified=solidified or [],
        outcome_quality=outcome_quality,
    )
    engine = AuditEngine()
    report = engine.audit(inp)
    return {
        "quality_score": report.quality_score,
        "pattern_detected": report.pattern_detected,
        "actions": [
            {
                "action": a.action,
                "target": a.target,
                "confidence": a.confidence,
                "reason": a.reason,
            }
            for a in report.actions
        ],
        "summary": report.summary,
    }
