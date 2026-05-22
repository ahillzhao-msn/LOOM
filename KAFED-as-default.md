# KAFED as Default Hermes Engine — 部署指引

> **基線**: KAFED 已是獨立 Python 包（`~/KAFED/`, v2.0.0），五層架構（D/E/F/A/K）已實現。
> 本指引將 Hermes Agent 的現有技能逐一指向 KAFED，完成飛輪系統的全面部署。
> 
> 不同於舊設計（HTTP 服務 + 獨立 Runner），當前 KAFED 使用 **import 模式**——同進程直接導入，零網絡開銷。

## 四步計劃總覽

| 步驟 | 目標 | 關鍵動作 | 
|:---|:---|:---|
| **Step 1** | K 層整合 | knowledge-management ⇒ KAFED knowledge/ |
| **Step 2** | F 層整合 | discern-engine/router ⇒ KAFED finder/ |
| **Step 3** | E+D 層整合 | orchestrator + pulse_manager ⇒ KAFED director/ + executor/ + analyzer/ |
| **Step 4** | 全鏈測試 | 每層單元測試 → 集成測試 → 飛輪驗證 |

## 前提條件

```bash
# KAFED 項目正常
ls ~/KAFED/src/kafed/*/__init__.py
# 應顯示: director/ executor/ finder/ analyzer/ knowledge/ client/ kpak/

# Hermes 技能同步
ls ~/.hermes/skills/meta/KAFED/src/kafed/*/__init__.py
# 同上

# Python import 可用
cd ~/KAFED && python3 -c "import sys; sys.path.insert(0,'src'); from kafed.director import EvalScorer; print('OK')"
```

---

## Step 1：K 層整合 — knowledge-management ⇒ KAFED knowledge/

### 1.1 更新 import 路徑

`~/.hermes/skills/human-like/core/knowledge-management/` 中所有 `from kafed.server.X` 改為 `from kafed.knowledge.X.Y`：

```python
# 舊
from kafed.server.config import get_config
from kafed.server.embedding import get_model
from kafed.server.chunker import chunk_document

# 新  
from kafed.config import get_config
from kafed.knowledge.rag.embedding import get_model
from kafed.knowledge.rag.chunker import chunk_document
```

### 1.2 驗證知識攝入/查詢

```python
from kafed.client.local_backend import KafedLocalBackend
bridge = KafedLocalBackend()
result = bridge.query("PM 維護工單", domain="SAP_PM")
assert len(result.get("results", [])) > 0
```

---

## Step 2：F 層整合 — discern-engine/router ⇒ KAFED finder/

### 2.1 更新 discern-engine 技能

`~/.hermes/skills/human-like/core/discern-engine/` 中的 `router.py`、`worker_manager.py`、`hermes_explorer.py` 保持向後兼容，但核心邏輯已遷移至 `~/KAFED/src/kafed/finder/`。

### 2.2 測試 find_partners

```python
from kafed.finder import find_partners
result = find_partners("SAP PM 維護工單分析", budget="any")
assert len(result.candidates) > 0
```

---

## Step 3：E+D 層整合 — orchestrator ⇒ KAFED director/ + executor/

### 3.1 更新 orchestrator SKILL.md

EVAL 引用指向 `kafed.director.eval`，決策樹指向 `kafed.director.decision`，策略指向 `kafed.director.strategy`。

### 3.2 脈動遷移

`pulse_manager.py` 的核心邏輯由 `kafed.analyzer.pulse` 取代。

```python
# 新脈動入口
from kafed.analyzer import pulse, status as pulse_status
result = pulse()  # 等價於舊 pulse_manager.py
```

### 3.3 執行引擎

```python
from kafed.executor import ExecutorEngine, DAGTask
engine = ExecutorEngine()
summary = engine.execute_dag([
    DAGTask(id="T1", description="step 1", depends_on=[]),
    DAGTask(id="T2", description="step 2", depends_on=["T1"]),
])
```

---

## Step 4：全鏈測試

### 4.1 層間通信測試

```python
# Director → Executor
from kafed.director import EvalScorer, DecisionTree, DecisionContext
from kafed.executor import ExecutorEngine

score = EvalScorer.from_description("分析 SAP PM 數據")
print(f"Tier: {score.tier}")

ctx = DecisionContext(task_description="查詢維護工單")
decision = DecisionTree.evaluate(ctx)
print(f"Decision: {decision.decision.value}")

# Executor → Finder
from kafed.finder import find_partners
result = find_partners(ctx.task_description)
print(f"Candidates: {len(result.candidates)}")
```

### 4.2 飛輪循環測試

```python
# Director → Executor → Knowledge → Analyzer
from kafed.director import Planner, TaskPlan
from kafed.executor import ExecutorEngine
from kafed.analyzer import AnalyzerEngine

# 建立計劃
plan = Planner.create_plan("知識分析任務")
# 執行
engine = ExecutorEngine()
report = engine.execute_direct([("test", "echo 'KAFED flywheel'", "script")])
print(f"Exec: {report.status}")

# 分析
analyzer = AnalyzerEngine()
cycle = analyzer.cycle()
print(f"Analyzer: {cycle.pulse_result.get('status')}")
```

### 4.3 技能引用完整性檢查

```bash
# 確保所有技能仍可加載
grep -rn "from kafed\." ~/.hermes/skills/human-like/ --include="*.py" --include="*.md" | grep -v __pycache__
# 無舊 kafed.server 殘留
grep -rn "kafed\.server" ~/.hermes/skills/ --include="*.py" --include="*.md" | grep -v __pycache__
# 應該=0（除非 server/__init__.py 向後相容 shim）
```

---

## 管線前後的架構對比

| 維度 | 接管前 | 接管後 |
|:---|:---|:---|
| **EVAL 評分** | orchestrator SKILL.md 硬編碼 | `kafed.director.eval.EvalScorer` |
| **決策樹** | SOUL.md 文字描述 | `kafed.director.decision.DecisionTree` |
| **模型路由** | router.py（discern-engine 內） | `kafed.finder.router.find_partners()` |
| **任務執行** | orchestrator 循環 + DAG | `kafed.executor.ExecutorEngine` |
| **脈動排程** | pulse_manager.py（465行） | `kafed.analyzer.pulse.pulse()` |
| **模式發現** | 不存在 | `kafed.analyzer.patterns.PatternDetector` |
| **湧現檢測** | 不存在 | `kafed.analyzer.emergence.EmergenceCalculator` |
| **知識 Layer** | KAFED RAG（server/） | `kafed.knowledge.rag.*` |
| **知識 classify** | discern-engine 內 | `kafed.knowledge.classify.classify` |
