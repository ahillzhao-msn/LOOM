"""Director 層動作註冊——Pipeline 步驟 + 內部編排。"""
from kafed.action_registry import registry, Action


def _eval_fn(input_data=None):
    from kafed.director.eval import EvalScorer
    scorer = EvalScorer()
    return scorer.score(input_data=input_data)


def _decide_fn(context=None):
    from kafed.director.decision import DecisionTree
    tree = DecisionTree()
    return tree.decide(context=context)


def _solidify_fn(insight="", target=""):
    from kafed.entry import solidify
    return solidify(insight=insight, target=target)


def _plan_fn(task="", domain=""):
    from kafed.orchestrator import Orchestrator
    o = Orchestrator()
    return o.plan(task=task, domain=domain)


# ── Pipeline 步驟（SOUL Level）─────────────

registry.register(Action(id="pipeline_ask",       code="D",
    labels={"zh": "問", "en": "Ask"},
    description="5W1H 問題分解"))

registry.register(Action(id="pipeline_hexagram",  code="D",
    labels={"zh": "卦", "en": "Hexagram"},
    description="YiCeNet 持續感知"))

registry.register(Action(id="pipeline_recall",    code="D",
    labels={"zh": "召", "en": "Recall"},
    description="KM 知識召回"))

registry.register(Action(id="pipeline_eval",      code="D",
    labels={"zh": "評", "en": "Eval"},
    description="EVAL 帶文脈評估", fn=_eval_fn))

registry.register(Action(id="pipeline_scope",     code="D",
    labels={"zh": "界", "en": "Scope"},
    description="Scope 檢查"))

registry.register(Action(id="pipeline_decision",  code="D",
    labels={"zh": "決", "en": "Decide"},
    description="自決決策樹", fn=_decide_fn))

registry.register(Action(id="pipeline_orchestrate", code="D",
    labels={"zh": "編", "en": "Orch"},
    description="任務編排", fn=_plan_fn))

registry.register(Action(id="pipeline_respond",   code="D",
    labels={"zh": "應", "en": "Respond"},
    description="生成回應"))

registry.register(Action(id="pipeline_solidify",  code="D",
    labels={"zh": "固", "en": "Solidify"},
    description="固化與稽查", fn=_solidify_fn))

# ── Director 內部 ──────────────────────────

registry.register(Action(id="pipeline_commit",    code="D",
    labels={"zh": "承", "en": "Commit"},
    description="Pipeline 步驟承諾"))

registry.register(Action(id="pipeline_plan",      code="D",
    labels={"zh": "解", "en": "Plan"},
    description="任務分解規劃", fn=_plan_fn))

registry.register(Action(id="pipeline_meta",      code="D",
    labels={"zh": "選", "en": "Sel"},
    description="Pipeline 選擇 & 啟動"))

registry.register(Action(id="pipeline_hex_predict", code="D",
    labels={"zh": "卦", "en": "Hex"},
    description="YiCeNet 卦象預測"))