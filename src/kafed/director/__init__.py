"""
KAFED Director — 戰略規劃、任務分解、EVAL、三省。

總監層是 KAFED 五層飛輪的頂層：
  接收輸入 → EVAL → 自決樹 → 三省 → 任務分解 → 發送給 Executor
"""

from kafed.director.eval import EvalScore, EvalScorer, F1Scope, F2People, F3Freshness, F4Risk, F5TokenCost
from kafed.director.decision import DecisionTree, Decision, DecisionContext, DecisionResult, CostLevel, Reversibility
from kafed.director.strategy import StrategySelector, StrategyConfig, StrategyDecision, Orientation
from kafed.director.planner import Planner, TaskPlan, SubTask, TaskStatus, ExecutionStrategy
from kafed.director.protocol import DispatchOrder, ExecutionReport, KnowledgeDeposit

__all__ = [
    # eval
    "EvalScore", "EvalScorer", "F1Scope", "F2People", "F3Freshness", "F4Risk", "F5TokenCost",
    # decision
    "DecisionTree", "Decision", "DecisionContext", "DecisionResult", "CostLevel", "Reversibility",
    # strategy
    "StrategySelector", "StrategyConfig", "StrategyDecision", "Orientation",
    # planner
    "Planner", "TaskPlan", "SubTask", "TaskStatus", "ExecutionStrategy",
    # protocol
    "DispatchOrder", "ExecutionReport", "KnowledgeDeposit",
]
