# KAFED v3.0 — Knowledge Agent Framework

> **Decision support, not execution. Knowledge that learns.**

<p align="center">
  <img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-yellow.svg">
  <img alt="Python 3.10+" src="https://img.shields.io/badge/Python-3.10+-blue.svg">
  <img alt="Chunks" src="https://img.shields.io/badge/Chunks-143K+-green.svg">
  <img alt="Domains" src="https://img.shields.io/badge/Domains-47-purple.svg">
  <img alt="Version" src="https://img.shields.io/badge/Version-4.0.0-red.svg">
  <img alt="Tests" src="https://img.shields.io/badge/Tests-PASS-brightgreen.svg">
</p>

---

## What Is KAFED

KAFED is a **decision-support engine** for AI agents. It doesn't execute tasks — it enriches the agent's context so the agent makes better decisions, faster, with less token waste.

Every turn, KAFED performs four mandatory steps and injects the result into the agent's context:

```
User Input → [5W1H Decomposition → YiCeNet Hexagram → Knowledge Recall → EVAL Scoring]
                → Agent acts freely (tools, model selection, task splitting)
                    → KAFED solidifies insights back into the knowledge base
```

The knowledge base is a self-organizing RAG system: it classifies, quality-filters, detects drift, and shares knowledge across instances via `.kpak` packages.

---

## Before / After

| Metric | Without KAFED | With KAFED v3 |
|--------|--------------|---------------|
| **Context quality** | Agent starts from scratch each turn | 5W1H + hexagram guidance + relevant knowledge recalled |
| **Token waste** | ~40% spent re-discovering known facts | Knowledge injected upfront, no re-discovery |
| **Model selection** | Hardcoded or guesswork | Finder's 3-vector aggregation (task ⊗ model ⊗ status) |
| **Knowledge retention** | Lost between sessions | Auto-solidified into RAG, retrievable next session |
| **Task complexity awareness** | None | EVAL 5-dimension scoring (Tier 1–3) |
| **Knowledge decay** | Stale facts never cleaned | E1-E5 flywheel events: drift detection, dedup, staleness |

---

## Quick Start

### Install

```bash
git clone https://github.com/ahillzhao-msn/KAFED.git
cd KAFED

# One-command bootstrap
bash scripts/install/kafed-bootstrap.sh

# Symlink Hermes tools
bash scripts/install/symlink-tools.sh
```

The bootstrap auto-detects your environment (Hermes venv, WSL, GPU, llama-server) and configures everything.

### Basic Usage

```python
from kafed import recommend, solidify, find_partners

# Every turn: get decision context
rec = recommend("SAP PM工单IW32增强")
print(rec.inject())
# ══════ KAFED 决策素材 ══════
# ▎5W1H: what=分析 where=SAP PM 工单
# ▎卦: ䷄ 需 ⚊⚊⚊⚋⚊⚋ — 等待时机
# ▎知识召回: 8 条 (含 IW32 exit, 增强模式)
# ▎难度: Tier 1  Score=1

# When splitting tasks: find best models
results = find_partners([
    "Python code audit: embedding module",
    "Refactor: Strategy pattern for backends",
])
for r in results:
    best = r.candidates[0]
    print(f"T{r.task_index+1}: {best.name} score={best.match_score:.3f}")

# After responding: save learnings
solidify("IW32增强: 先读现有exit再扩展APPEND", domain="SAP_PM")
```

### Hermes Agent Integration

Add to your SOUL.md:

```
每轮开始 → kafed_recommend(user_input) → 注入上下文
  → Agent 自由行动（可调 kafed_find_partners 匹配模型）
    → kafed_solidify(insight)
```

Or call directly as Hermes tools: `kafed_recommend`, `kafed_find_partners`, `kafed_solidify`, `kafed_query`, `kafed_ingest`.

### Knowledge Packages

```bash
python -m kafed.kpak pack SAP_PM          # export domain
python -m kafed.kpak unpack SAP_PM.kpak   # import to another instance
python -m kafed.kpak info SAP_PM.kpak     # inspect contents
```

---

## Architecture

KAFED has four layers — a **decision-support frontend** and a **learning backend**:

```
┌── Frontend (every turn) ──┐          ┌── Backend (async) ──┐
│                            │          │                      │
│  Director                  │          │  Analyzer            │
│    recommend()             │────────► │    solidify()        │
│    5W1H → Hexagram →       │          │    session audit     │
│    Recall → EVAL           │          │    knowledge audit   │
│                            │          │                      │
│  Finder (on-demand)        │          │  Scheduler           │
│    find_partners()         │          │    task registry     │
│    heartbeat probes        │          │    WSL compensation  │
│    explorer scans          │          │                      │
│                            │          │                      │
│  Knowledge (passive)       │◄──────── │  Flywheel (E1-E5)    │
│    RAG + classify          │          │    centroid rebuild  │
│    ContextProvider         │          │    drift detection   │
│    .kpak sharing           │          │    dedup + staleness │
└────────────────────────────┘          └──────────────────────┘
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full technical design.

---

## Core Principles

1. **Agent owns decisions, KAFED provides context** — the engine never replaces the agent's judgment. It enriches the soil, doesn't plant the seeds.

2. **Embedding space is the universal language** — classification, retrieval, model matching all happen in vector space. No hardcoded keyword rules.

3. **Knowledge is alive** — the flywheel detects drift, staleness, and growth automatically. Knowledge decays if unused, strengthens if revisited.

4. **Privacy-first sharing** — `.kpak` packages share structure and centroids, never raw data or model weights. Export with confidence.

5. **Quality over quantity** — every chunk is scored. Noise is filtered before storage, not during retrieval.

---

## Loom (织机) — Conversation-Level Session Management

Loom weaves scattered turns into coherent conversations, providing the flywheel with complete decision trajectories.

```
Conversation (logical entity) → 1:n → Session (technical slice) → 1:n → Turn (atomic round)
```

**Key features:**
- **Cross-session continuity** — Conversations survive agent restarts, idle timeouts, and system reboots
- **Full trajectory capture** — Every turn records hexagram, knowledge recall, EVAL score, solidify events, token usage
- **Reward aggregation** — On close, produces a rich reward signal package for the flywheel (correction rate, hexagram evolution, knowledge reuse, token efficiency)
- **Auto-integration** — `solidify()` automatically records to the active conversation; `close_conversation()` submits to YiCeNet's flywheel
- **Shuttle visualization** — Four weave modes: flow chain, hexagram trail, session tapestry, conversation tapestry

See [docs/loom-architecture.md](docs/loom-architecture.md) for the full design and API reference.

---

## Personal AI Manifesto

> KAFED was born from a simple frustration: AI agents should remember, but they shouldn't need to be retrained. They should learn from every conversation, but they shouldn't drown in noise. They should make decisions with context, not guesswork.
>
> The name comes from the Arabic root ق-ف-د (Q-F-D) — to bind, to knot, to tie knowledge together. KAFED doesn't just store facts. It weaves them into a structure that the agent can navigate.
>
> We believe that the best AI assistant is not the one with the most parameters — it's the one that wastes the fewest tokens re-learning what it already knows.
>
> **知之为知之，不知为不知，是智也。**
> *To know what you know, and know what you don't — that is wisdom.*

---

## Dependencies

- **Python 3.10+**
- **ChromaDB** — vector database
- **sentence-transformers** — bge-small-en-v1.5 (384d)
- **NumPy**, **PyYAML**
- **PyTorch** (optional) — GPU embedding

---

## Related

- [YiCeNet](https://github.com/ahillzhao-msn/YiCeNet) — I-Ching neural network, the intuition layer

---

[MIT](LICENSE) © ahillzhao-msn
