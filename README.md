# KAFED — Knowledge Agent Framework for Embedded Data

**K**nowledge → **A**nalysis → **F**inder → **E**xecutor → **D**irector

五層智能飛輪體系（從右往左讀）。輕量 RAG 服務 + 事件驅動知識飛輪 + 自主分析 + 智能路由 + 戰略規劃。

## 五層架構

```
K — Knowledge     知識管理、向量圖譜、記憶晉升     ✅ 現有（RAG + classify + flywheel）
A — Analysis      全自主數據分析、模式發現、洞察    ❌ 待建設
F — Finder        模型發現、三維聚合路由          ⚠️ 雛形（router + worker_manager）
E — Executor      任務執行、DAG調度、模型調用     ⚠️ 雛形（dag_scheduler）
D — Director      戰略規劃、任務分解、EVAL三省    ❌ 待建設（將吸收 Hermes strategic-awareness + orchestrator）
```

## 安裝

```bash
pip install kafed

# 如需 HTTP 服務器：
pip install "kafed[server]"
```

## 快速开始

```python
from kafed.client.local_backend import KafedLocalBackend

backend = KafedLocalBackend()

# 摄入知识
backend.ingest_text(
    "# SAP PM\n\n通知类型 M1 是故障报告，M2 是维护请求...",
    filename="sap_pm_notes.md",
    domain="SAP_PM",
)

# 查询
result = backend.query("What is M1 notification type?", domain="SAP_PM")
for res in result["results"]:
    print(f"[{res['score']:.3f}] {res['content'][:100]}")
```

## CLI

```bash
# 摄入文档
kafed ingest doc.md --domain SAP_PM

# 查询
kafed query "notification types"

# 启动服务器
kafed start --host 0.0.0.0 --port 8765
```

## 架构

```
src/kafed/
├── server/        # FastAPI RAG 服务
│   ├── quality.py      # 文档清洗 + 质量评分
│   ├── chunker.py      # 标题链层次分块
│   ├── embedding.py    # bge-small 嵌入
│   ├── vector_store.py # Chroma 向量库
│   ├── rag_engine.py   # 检索排序域匹配
│   └── event_checker.py# 事件飞轮 E1-E4
├── client/        # 客户端双模式
│   ├── http_client.py  # HTTP 远程调用
│   ├── local_backend.py# 本地直接导入（零进程）
│   └── cli.py          # 命令行工具
└── kpak/          # 知识包打包系统
    ├── pack.py
    └── unpack.py
```

## 事件飞轮

| 事件 | 触发条件 | 动作 |
|------|----------|------|
| E1 | ingest 后新块 ≥10 | 重建域 centroid |
| E2 | 累计反馈 ≥50 | 更新评估模型 |
| E3 | 某域条目 ≥200 | 打包 .kpak |
| E4 | 同 QA 成功 ≥10 | 写入 SFT 缓冲区 |

## 许可

MIT
