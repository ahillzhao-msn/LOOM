# KAFED — 智能飞轮引擎

Knowledge-Aware Federated Execution & Decision

KAFED 是一个**五层智能飞轮体系**（从右往左读）：

```
K — Knowledge（知识层）：向量知识库、RAG、centroid域分类、飞轮事件
A — Analyzer（分析层）：脉动调度、模式发现、涌现检测、任务规划
F — Finder（查找层）：模型注册表、三维聚合路由、语境内嵌空间
E — Executor（执行层）：DAG任务排程、调度分发、监督反馈环
D — Director（战略层）：EVAL评估、决策树、策略选择、任务分解
```

## 架构

```
用户输入 → D(战略规划) → 子任务列表
               ↓
           F(模型发现) → 每个子任务匹配最佳模型
               ↓
           E(DAG执行) → 自动排程 + 依赖管理 + 反馈环
               ↓
           A(分析吸收) → 结果判断 + 记忆固化建议
               ↓
           K(知识沉淀) → 向量入库 + centroid合并 + 飞轮自检
               ↓
           ←──────── 回到 D，继续下一轮 ────────→
```

### 设计六原则

1. **向量库是主存储** — 不是附屬品，是知識的物理內核
2. **Centroid 是內化結構** — 不存 raw weights，存數學結構
3. **RAG 即時可用** — 攝入即檢索，無需 SFT/訓練
4. **事件驅動非閾值** — 自檢飛輪（E1-E5），無硬編碼定時任務
5. **分享數學結構非權重** — `.kpak` 分享 centroid 而非模型權重
6. **質量第一不過度工程** — 寧慢勿髒

## 快速开始

```bash
# 1. 克隆
git clone https://github.com/ahillzhao-msn/KAFED.git
cd KAFED

# 2. 安装
bash setup.sh

# 3. 配置
cp kafed.yaml.example kafed.yaml  # 编辑 kafed.yaml
cp .env.example .env               # 填入 API 密钥

# 4. 验证
source .venv/bin/activate
python -c "from kafed.config import get_config; print(get_config().show())"
```

## 依赖

- Python 3.10+
- PyTorch（可选，GPU 加速 embedding）
- ChromaDB（向量数据库）
- sentence-transformers（嵌入模型）
- NumPy

## 许可

MIT License

## 关联项目

- [YiCeNet](https://github.com/ahillzhao-msn/YiCeNet) — 易策网络，KAFED 的卦象预判组件
