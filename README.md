# KAFED — 智能飞轮引擎

Knowledge-Aware Federated Execution & Decision

KAFED 是一个**五层智能飞轮体系**，从右往左读：

```
K — Knowledge（知识层）
A — Analyzer（分析层）
F — Finder（查找层）
E — Executor（执行层）
D — Director（战略层）
```

每一层是一个齿轮，数据在其中循环流动，形成自我强化的飞轮。

---

## 设计哲学

KAFED 的根基是三道三层：

```
道 — 顺应自然，不妄为
法 — 制度规则，Pipeline·三省·四问
兵 — 执行策略，先胜后战，一步一验
```

六条工程原则：

1. **向量库是主存储** — 不是附属品，是知识的物理内核
2. **Centroid 是内化结构** — 不存 raw weights，存数学结构
3. **RAG 即时可用** — 摄入即检索，无需 SFT/训练
4. **事件驱动非阈值** — 自检飞轮（E1-E5），无硬编码定时任务
5. **分享数学结构非权重** — `.kpak` 分享 centroid 而非模型权重
6. **质量第一不过度工程** — 宁慢勿脏

---

## 五层架构

### 飞轮循环

```
用户输入 → D(战略规划) → 子任务列表
               │
               ▼
           F(模型发现) → 每个子任务匹配最佳模型
               │
               ▼
           E(DAG执行) → 自动排程 + 依赖管理
               │
       ┌───────┴───────┐
       │               │
   任务完成          任务失败
       │               │
   FeedbackDecision   FeedbackDecision
   .CONTINUE          .REPLAN / .ABORT
       │               │
   继续 DAG       Director 重新规划或中止
               │
               ▼
           A(分析吸收) → 结果判断 + 记忆固化建议
               │
               ▼
           K(知识沉淀) → 向量入库 + centroid合并 + 飞轮自检
               │
               ▼
       ←─── 回到 D，继续下一轮 ────→
```

### 每层职责

| 层 | 职责 | 核心模块 |
|----|------|---------|
| **D** Director | EVAL 评估、决策树、策略选择、Pipeline 编排 | `director/eval.py`, `decision.py`, `strategy.py`, `planner.py`, `pipeline.py` |
| **F** Finder | 模型注册表、三维聚合路由、语境内嵌空间 | `finder/registry.py`, `router.py`, `explorer.py`, `context_space.py` |
| **E** Executor | DAG 任务排程、调度分发、**监督反馈环** | `executor/dag.py`, `dispatcher.py`, `engine.py` |
| **A** Analyzer | 脉动调度、任务稽查引擎、KB 离线稽核、模式检测 | `analyzer/{pulse,audit,kb_audit}.py` |
| **K** Knowledge | 向量知识库、RAG、centroid 域分类、飞轮事件 E1-E5 | `knowledge/rag/`, `classify/`, `flywheel/`, `quality/` |

### 关键机制：监督反馈环

Executor 拥有 DAG 自动排程的全权，但每完成/失败一个任务就通过回调通知 Director。

```python
from kafed.executor.engine import FeedbackAction, FeedbackDecision

def my_callback(task_id, status, result):
    if status == "failed":
        return FeedbackDecision(action=FeedbackAction.REPLAN,
                                message=f"{task_id} 失败")
    return FeedbackDecision(action=FeedbackAction.CONTINUE)

from kafed.orchestrator import plan, execute
p = plan("审计知识库", domain="SAP_PM")
results = execute(p, director_callback=my_callback)
```

默認策略：首次失败自动 REPLAN，后续失败 CONTINUE——给第一次机会，但不让单点故障阻塞整体。

---

## 全局配置

KAFED 的全套配置集中在 `kafed/config.py`，所有子模块不从环境变量或硬编码读取。

### 优先级

```
环境变量 > YAML 文件 > 代码默认值
```

### 配置模板

```bash
cp kafed.yaml.example kafed.yaml  # 编辑路径、阈值
cp .env.example .env               # 编辑 API 密钥
```

### 密钥隔离

敏感信息（API Key）由 `KafedSecrets` 管理，永不出现在 `show()` 中：

```python
from kafed.config import get_config, get_secrets

cfg = get_config()
print(cfg.show())          # 密钥显示为 [REDACTED]

secrets = get_secrets()
key = secrets.deepseek_api_key  # 从 .env 或环境变量读取
```

### 环境变量覆盖

所有配置项可被环境变量覆盖：

```bash
export KAFED_DATA_DIR=/custom/data/path
export KAFED_FAST_ROUTE_MAX_WORKERS=10
export KAFED_LOG_LEVEL=DEBUG
python -c "from kafed.config import get_config; print(get_config().show())"
```

完整列表见 `kafed.yaml.example` 每个字段的 `env:` 注释。

---

## 快速开始

```bash
# 1. 克隆
git clone https://github.com/ahillzhao-msn/KAFED.git
cd KAFED

# 2. 安装（自动创建虚拟环境 + 安装依赖 + 数据目录）
bash setup.sh

# 3. 下载 embedding 模型（可选，首次查询时会自动下载）
bash scripts/download_models.sh

# 4. 配置
cp kafed.yaml.example kafed.yaml   # 编辑路径、阈值
cp .env.example .env                # 填入 API 密钥

# 5. 激活 + 验证
source .venv/bin/activate
python -c "from kafed.config import get_config; print(get_config().show())"
```

## API 速查

```python
# 配置
from kafed.config import get_config, get_secrets
cfg = get_config()
cfg.show()                     # 查看所有配置
cfg.data_dir                   # 数据目录
cfg.centroids_filename         # 文件名（可配置）
secrets = get_secrets()
secrets.deepseek_api_key       # API 密钥（从 .env）

# Director → Finder → Executor 全链
from kafed.orchestrator import plan, execute, absorb, dispatch_for, needs_dispatch

p = plan("分析 SAP PM 模块", domain="SAP_PM")
# → Finder 自动匹配最佳模型
# → 返回 Plan(子任务 + 模型列表)

results = execute(p)
# → Executor DAG 调度
# → 每个子任务按依赖顺序执行
# → 默认反馈：首次失败 replan，后续 continue

report = absorb(results, source="audit")
# → Analyzer 吸收 + KM 固化建议
# → 失败任务自动推入 backlog

# 任务委派到子代理
dr = dispatch_for(task_result, goal="审计代码")
import json
params = json.loads(dr.output)   # 含 KAFED context 注入
delegate_task(**params)           # 子代理自动可 import kafed

# Pipeline
from kafed.director.pipeline import SOUL_CORE, PipelineRunner
runner = PipelineRunner(SOUL_CORE)
while True:
    step = runner.next_step()
    if not step: break
    # execute step
    runner.complete()

# kpak 知识包
from kafed.kpak.pack import pack_domain, list_kpak
from kafed.kpak.unpack import unpack_kpak

# 导出 SAP_PM 域为可分享的 .kpak
pack_domain("SAP_PM")   # → ~/.kafed/data/kpak/SAP_PM.kpak

# 导入他人的 .kpak
unpack_kpak("path/to/SAP_PM.kpak")

# 查看所有可用包
list_kpak()

# 全局日志
from kafed.log import logger
logger.info("任务完成", extra={"task_id": "audit_001"})
```

## 目录结构

```
~/KAFED/
├── src/kafed/
│   ├── config.py           — 全局配置 (KafedConfig + KafedSecrets)
│   ├── log.py              — 全局日志
│   ├── orchestrator.py     — 五层编排器
│   ├── director/           — 战略决策层 (7 模块)
│   ├── finder/             — 模型发现层 (5 模块)
│   ├── executor/           — DAG 执行层 (4 模块 + 监督反馈环)
│   ├── analyzer/           — 分析脉动层 (pulse + audit + kb_audit)
│   ├── knowledge/          — 知识 RAG 层 (12 模块)
│   ├── kpak/               — 知识包导出/导入
│   └── client/             — CLI + FlowVisualizer
├── templates/               — SOUL 认知架构模板
├── archive/                 — 历史文档归档
├── scripts/                — 工具脚本
├── setup.sh                — 一键安装
├── kafed.yaml.example      — 配置模板
├── .env.example            — 密钥模板
├── tests/                  — pytest 测试 (11 through)
└── README.md
```

运行数据（不在 git 中）：

```
~/.kafed/                   ← 数据根 (可配置)
├── data/chroma/            ← Chroma 向量库
├── data/kpak/              ← 导出的知识包
├── data/logs/              ← 日志文件
├── roster.yaml             ← 模型池
├── backlog.json            ← 任务待办
└── task_registry.yaml      ← 持久化任务
```

## 依赖

- Python 3.10+
- ChromaDB（向量数据库）
- sentence-transformers（bge-small-en-v1.5 嵌入模型）
- NumPy
- PyYAML
- PyTorch（可选，GPU 加速 embedding）

## 许可

MIT License

## 关联项目

- [YiCeNet](https://github.com/ahillzhao-msn/YiCeNet) — 易策网络，基于易经的卦象预判神经网络，KAFED Pipeline 的直觉层
