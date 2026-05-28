"""KAFED Director — 決策支援層。

唯一入口：recommend(user_input) → Recommendation
三步強制：卦(YiCeNet) → 召(ContextProvider) → 評(EvalScorer)
"""

from kafed.director.recommend import recommend, Recommendation
from kafed.director.eval import EvalScore, EvalScorer, F1Scope, F2People, F3Freshness, F4Risk, F5TokenCost

__all__ = [
    "recommend", "Recommendation",
    "EvalScore", "EvalScorer", "F1Scope", "F2People", "F3Freshness", "F4Risk", "F5TokenCost",
]
