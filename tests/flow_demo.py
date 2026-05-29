#!/usr/bin/env python3
"""LOOM v3.0 Flow Demo — 公交站牌風格展示。

兩種模式對比：
  compact  — 箭頭串聯（回應標頭用）: D問(SAP) → D卦(Q=0.72) → D召(8條) → D評(T3)
  detailed — 公交站牌（詳細追蹤用）: chain() 樹狀站點
"""

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from loom.flow import set_flow_enabled, chain, divider, hop, stop
from loom.director.hexagram import hexagram_display, hexagram_chain_compact

set_flow_enabled(True)


def demo_case1():
    """Case 1: 簡單任務 — SAP PM 工單分析。"""
    divider("══════ Case 1: SAP PM 工單分析 ══════")
    user_input = "SAP PM工單IW32增強需要分析現有代碼並加入新字段"

    # ── compact 模式（箭頭鏈）──
    print(f"  [compact] D問(PM工單) -> D卦({hexagram_display(5)}) -> D召(3條) -> "
          "D評(T1) -> Agent(直行) -> D固(KM)")
    print()

    # ── detailed 模式（公交站牌）──
    chain("LOOM 決策素材", [
        ("D", "問", "5W1H: what=分析 where=SAP PM 工單"),
        ("D", "卦", f"{hexagram_display(5)} — 需卦：等待時機"),
        ("D", "召", "ContextProvider → RAG+Wiki 全源召回 3 條"),
        ("D", "評", "EVAL: F1=1 F3=1 F4=1 → Tier 1"),
    ], end="素材注入 Agent context")

    chain("Agent 行動", [
        ("🧠", "判斷", "Tier 1 → 不需拆子任務，直接執行"),
        ("📖", "讀取", "IW32 源碼分析"),
        ("✏️", "生成", "回應 — 增強方案"),
    ], end="回應完成")

    chain("LOOM 閉環", [
        ("💡", "洞察", "IW32 增強: 先讀現有 exit 再擴展"),
        ("💾", "固化", "solidify → KM 寫入"),
        ("🔄", "飛輪", "觸發 E1 ingest 事件"),
    ], end="KM 閉環完成")

    divider("Case 1 完成")


def demo_case2():
    """Case 2: 複雜任務 — 重構 LOOM embedding。"""
    divider("══════ Case 2: 重構 LOOM embedding ══════")
    user_input = "重構LOOM的embedding模組：代碼審計 + 多後端Strategy + 補測試"

    # Case 2 compact — 含卦鏈
    chain_ids = [1, 44, 33, 12]  # 乾→姤→遯→否
    print(f"  [compact] D問(重構embedding) -> D卦({hexagram_display(1)}) -> "
          f"D召(8條) -> D評(T3) -> "
          f"F搜(3向量) -> F配(cosine) -> F聚 -> "
          f"遣(T1:sonnet/T2:ds-pro) -> D固(KM)")
    print(f"            卦鏈: {hexagram_chain_compact(chain_ids)}")
    print()

    # ── detailed ──
    chain("LOOM 決策素材", [
        ("D", "問", "5W1H: what=重構 where=LOOM embedding"),
        ("D", "卦", f"{hexagram_display(1)} — 乾卦：順勢而為 "
         f"[鏈: {hexagram_chain_compact(chain_ids)}]"),
        ("D", "召", "召回 8 條 (embedding.py, rag_engine.py, chunker.py)"),
        ("D", "評", "EVAL: F1=3(跨域) F3=2(探索) F4=2(修改) → Tier 3"),
    ], end="素材注入")

    chain("Agent 決策", [
        ("🧠", "判斷", "Tier 3 → 需拆 3 個子任務"),
        ("✂️", "T1", "embedding.py 代碼審計"),
        ("✂️", "T2", "Strategy 模式重構多後端"),
        ("✂️", "T3", "補全 pytest 單元測試"),
    ], end="準備匹配模型")

    # 實際調用 find_partners
    briefs = [
        "Python 代碼審計: embedding 模組安全與效能",
        "重構: Strategy 模式實現多 embedding 後端切換",
    ]

    chain("Finder 三向量聚合", [
        ("F", "搜", "3 個任務 → bge-small embedding 向量化"),
        ("F", "配", "cosine similarity: 任務⊗模型向量 矩陣運算"),
        ("F", "調", "ContextSpace 語境調製 (歷史成功模式偏向)"),
        ("F", "聚", "w_cap=0.5 + w_ctx=0.3 + w_sta=0.2 加權"),
    ], end="聚合完成")

    try:
        from loom.finder.router import Router
        router = Router()
        results = router.find_partners(briefs[:2])

        stations = []
        for r in results:
            top = r.candidates[0] if r.candidates else None
            if top:
                stations.append(("F", f"T{r.task_index+1}",
                    f"→ {top.name} ({top.provider}) score={top.match_score:.3f}"))
            else:
                stations.append(("F", f"T{r.task_index+1}", "→ 無匹配"))
        chain("匹配結果", stations, end=f"{len(results)}/2 完成")

    except Exception as e:
        hop("⚠️", "Finder", f"暫不可用: {str(e)[:60]}")
        chain("Fallback 建議", [
            ("F", "T1", "→ deepseek-v4-pro"),
            ("F", "T2", "→ claude-sonnet-4"),
            ("F", "T3", "→ deepseek-v4-flash"),
        ], end="手動分配完成")

    chain("Agent 執行 (delegate_task)", [
        ("🚀", "T1", "代碼審計 → deepseek-v4-pro"),
        ("🚀", "T2", "重構設計 → claude-sonnet-4"),
        ("🚀", "T3", "測試編寫 → deepseek-v4-flash"),
    ], end="3/3 子任務完成")

    chain("LOOM 閉環", [
        ("💡", "洞察", "embedding 後端: Strategy + Factory 模式"),
        ("💡", "教訓", "bge-small 384d 企業文檔同質性 → silhouette 低"),
        ("💾", "固化", "solidify → KM 寫入 2 條"),
        ("🔄", "飛輪", "觸發 centroid 更新 + KbAudit 稽核"),
    ], end="學習閉環完成")

    divider("Case 2 完成")


if __name__ == "__main__":
    demo_case1()
    print()
    demo_case2()
