# KAFED Architecture

> Version 4.0.0 · Decision-Support Engine · Loom · Director · Finder · Analyzer · Knowledge · Scheduler

---

## Table of Contents

1. [Design Philosophy](#1-design-philosophy)
2. [System Overview](#2-system-overview)
3. [Conversation Context (Loom)](#3-conversation-context-loom)
4. [Frontend: Decision Support](#4-frontend-decision-support)
5. [Finder: Model Matching](#5-finder-model-matching)
6. [Backend: Learning Loop](#6-backend-learning-loop)
7. [Knowledge Layer](#7-knowledge-layer)
8. [Scheduler & Compensation](#8-scheduler--compensation)
9. [Configuration System](#9-configuration-system)
10. [Knowledge Lifecycle](#10-knowledge-lifecycle)

---

## 1. Design Philosophy

KAFED is built on a three-level framework:

| Level | Principle | Engineering Manifestation |
|-------|-----------|--------------------------|
| **道** (Tao) | Follow nature, do not overreach | KAFED enriches context, Agent owns decisions |
| **法** (Method) | Rules and systems | Four mandatory steps per turn: 5W1H → Hexagram → Recall → EVAL |
| **兵** (Tactics) | Win first, then fight | All context gathered before Agent acts |

### Six Engineering Principles

1. **Agent owns decisions, KAFED provides context** — KAFED never replaces the agent's judgment. It enriches the decision surface.
2. **Embedding space is the universal language** — classification, retrieval, and model matching all operate in the same vector space. No hardcoded keyword rules.
3. **Vector store is primary storage** — ChromaDB is the physical kernel. All knowledge paths lead through it.
4. **Event-driven, not threshold-driven** — the flywheel (E1–E5) responds to change events, not hardcoded timers.
5. **Share structure, not weights** — `.kpak` packages share centroids and knowledge units, never raw data.
6. **Quality first** — every chunk is scored and filtered before storage.

---

## 2. System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    KAFED v3.0                                │
│                                                              │
│  ┌─────── Frontend (per turn) ───────┐                       │
│  │                                    │                      │
│  │  Director                          │                      │
│  │  ┌──────────────────────────────┐  │                      │
│  │  │ recommend(user_input)        │  │                      │
│  │  │  問: 5W1H decomposition     │  │                      │
│  │  │  卦: YiCeNet hexagram       │  │                      │
│  │  │  召: ContextProvider recall │  │                      │
│  │  │  評: EVAL 5-dim scoring     │  │                      │
│  │  └──────────────┬───────────────┘  │                      │
│  │                 │ inject()         │                      │
│  │                 ▼                  │                      │
│  │         Agent Context              │                      │
│  │                 │                  │                      │
│  │  Finder (on-demand)               │                      │
│  │  ┌──────────────────────────────┐  │                      │
│  │  │ find_partners(briefs)        │  │                      │
│  │  │ 3-vector aggregation:        │  │                      │
│  │  │ task⊗model⊗status → ranked   │  │                      │
│  │  └──────────────────────────────┘  │                      │
│  └────────────────────────────────────┘                      │
│                                                              │
│  ┌─────── Backend (async) ───────────┐                       │
│  │                                    │                      │
│  │  Analyzer                          │                      │
│  │  ┌──────────────────────────────┐  │                      │
│  │  │ solidify(insight) → KM write │  │                      │
│  │  │ session_end_audit()          │  │                      │
│  │  │ knowledge_audit()            │  │                      │
│  │  └──────────────────────────────┘  │                      │
│  │                                    │                      │
│  │  Scheduler                         │                      │
│  │  ┌──────────────────────────────┐  │                      │
│  │  │ TaskRegistry + TaskRunner    │  │                      │
│  │  │ WSL compensation             │  │                      │
│  │  │ builtin tasks (heartbeat,    │  │                      │
│  │  │   flywheel, explorer scan)   │  │                      │
│  │  └──────────────────────────────┘  │                      │
│  └────────────────────────────────────┘                      │
│                                                              │
│  ┌─────── Knowledge (passive) ────────┐                      │
│  │  RAG Engine · VectorStore          │                      │
│  │  ContextProvider · Classification  │                      │
│  │  Quality Filter · Flywheel Events  │                      │
│  │  kpak Export/Import                │                      │
│  └────────────────────────────────────┘                      │
└─────────────────────────────────────────────────────────────┘
```

### Data Flow (One Turn)

```
1. User Input
     │
2. Director.recommend()
     ├─ 5W1H: heuristic decomposition → structured problem view
     ├─ Hexagram: YiCeNet prediction (5W1H as input signal)
     ├─ Recall: ContextProvider → RAG + Wiki + Memory/Session/Skill
     └─ EVAL: F1-F5 scoring + hexagram modulation
     │
3. Recommendation.inject() → Agent context
     │
4. Agent acts freely
     ├─ Optional: find_partners(briefs) → model suggestions
     ├─ Uses Hermes tools, delegate_task, etc.
     └─ Generates response
     │
5. Analyzer.solidify(insight) → KM write + flywheel events
```

---

## 3. Conversation Context (Loom)

Loom (织机) is a cross-cutting conversation management layer that weaves individual turns into coherent conversations. It wraps the recommend → solidify cycle, providing:

- **Cross-session continuity** — Conversations survive agent restarts, idle timeouts, and system reboots
- **Full trajectory capture** — Every turn records hexagram, knowledge recall, EVAL score, solidify events, token usage
- **Reward aggregation** — On conversation close, produces a rich reward signal package for the YiCeNet flywheel
- **Shuttle visualization** — Four weave modes for inspecting conversation state at any granularity

### Architecture

```
Loom wraps the entire recommend → Agent → solidify cycle:

  ┌── Loom Conversation (logical entity) ──────────────────┐
  │                                                         │
  │  ┌── Session (technical slice) ──────────────────┐     │
  │  │                                                 │     │
  │  │  ┌───── Turn ─────┐  ┌───── Turn ─────┐       │     │
  │  │  │ recommend()    │  │ recommend()    │       │     │
  │  │  │ Agent acts     │  │ Agent acts     │  ...  │     │
  │  │  │ solidify() ───►│  │ solidify() ───►│       │     │
  │  │  └────────────────┘  └────────────────┘       │     │
  │  │                         ↑ session boundary    │     │
  │  └───────────────────────────────────────────────┘     │
  │                                                         │
  │  close_conversation()                                    │
  │    └─ reward_for_flywheel() → submit_trajectory()      │
  │       → YiCeNet flywheel buffer                         │
  └─────────────────────────────────────────────────────────┘
```

### Three Tiers

| Tier | Entity | Scope | Boundaries |
|------|--------|-------|------------|
| 1 | **Turn** | One recommend→act→solidify cycle | Natural turn boundary |
| 2 | **Session** | Technical slice | 30-min idle, restart, explicit close |
| 3 | **Conversation** | Logical entity, cross-session | 24-hour idle, semantic drift |

Tier 1–2 boundaries are technical (idle timeout, restart). Tier 3 is the only logical boundary — a conversation persists across idle and restart.

### Auto Integration

`solidify()` automatically records to the active Loom conversation if one exists — zero additional Agent code:

```python
from kafed.analyzer.solidifier import solidify

# If Loom has an active conversation, solidify auto-records
solidify("Found: architecture coupling too tight", domain="ARCH")
#     ↓
# loom.record_solidify(result)   ← automatic
```

`close_conversation()` submits the aggregated reward signal to YiCeNet's flywheel:

```python
from kafed.loom.manager import manager as loom

reward = loom.close_conversation()
# reward = {n_turns, hexagram_evolution, correction_rate, token_efficiency, ...}
```

### Shuttle (梭子)

Shuttle provides four weave modes for inspecting conversation state:

```
flow_chain(steps)       → D問 -> D卦(困) -> D召(K[3]) -> D評(T2)
hexagram_trail(ids)     → ䷮ → ䷉ · ䷉ → ䷲ (跳躍)
session_tapestry(s)     → Session abc123 · 3輪 · 2次固化 · 卦: ䷮→䷉
conversation_tapestry(c)→ 📜 Conversation def456 · 1 sessions · 2輪
```

### Producer/Consumer (YiCeNet Flywheel)

Loom is one of potentially many "external producers" feeding the YiCeNet flywheel:

```
                    submit_trajectory(data)
                    ┌──────────┐
Loom ──────────────►│          │
                    │  YiCeNet  │
Other producers ───►│  FLYWHEEL├──→ flywheel_buffer.jsonl ──→ RL train
                    │  _BUFFER │
                    └──────────┘
```

The API is non-fatal — `submit_trajectory()` silently no-ops when YiCeNet isn't installed.

### Key Design Decisions

1. **Agent zero-participation** — Loom operates transparently. `solidify()` auto-records; the Agent doesn't call loom APIs for basic lifecycle
2. **Non-fatal dependencies** — Neither Loom nor solidify() break when YiCeNet is absent
3. **Memory buffer, not persistent** — `FLYWHEEL_BUFFER` is an in-memory list consumed each cron cycle. No IO overhead during conversation
4. **Tuple compatibility** — `start_turn_from_recommend()` accepts both FlowEntry objects and simple tuples, so Agent code and tests can use either

See [docs/loom-architecture.md](docs/loom-architecture.md) for the full design and API reference.

---

## 4. Frontend: Decision Support

### 4.1 Director — `recommend()`

The single entry point. Called every turn before the Agent acts.

```
recommend(user_input) → Recommendation
  ├─ 5W1H: {what, why, who, where, when, how}
  ├─ hexagram: {id, symbol, six_lines, q_value, chain, candidates}
  ├─ knowledge_items: [ContextItem, ...]
  ├─ eval_score: EvalScore {tier, f1_scope, f3_freshness, f4_risk}
  └─ inject() → structured text for agent prompt
```

#### 5W1H Decomposition

Heuristic extraction from user input — no LLM involved. Each dimension is filled only when keywords match:
- **What**: action verbs (分析, 重構, audit, fix...)
- **Where**: domain hints (SAP, KAFED, Python, WSL...)
- **Why**: purpose patterns (為什麼, 為了, because...)
- **When**: urgency signals (緊急, ASAP, 今天...)
- **How**: method constraints (安全, 一步一驗, 最小改動...)

The 5W1H result serves as a richer input signal for YiCeNet than raw user text.

#### Hexagram (YiCeNet Integration)

YiCeNet predicts an I-Ching hexagram (1–64) with a Q-value confidence score. Each hexagram maps to:
- Unicode symbol (䷀–䷿, U+4DC0–U+4DFF)
- Six-line display (⚊⚋ monograms)
- Chinese name + English name
- Interpretation text

Hexagram chains form across turns: `䷀→䷫→䷠→䷋` (乾→姤→遯→否). The chain is tracked in `Recommendation.hexagram["chain"]` and passed back to `_step_hexagram()` in the next turn via `chain_history`.

Hexagram Q-value modulates EVAL risk scoring: Q > 0.8 lowers risk, Q < 0.3 raises it.

#### Knowledge Recall (ContextProvider)

Multi-source recall using the same embedding model (bge-small 384d) across all sources:

| Source | Match Method | Items | KAFED Role |
|--------|-------------|-------|-----------|
| RAG (ChromaDB) | Cosine similarity | Top-8 | Primary channel |
| Wiki | Cosine similarity (domain-filtered) | Top-4 | Same store |
| Memory | Hermes CLI query + embedding | Top-3 | Read-only |
| Sessions | Hermes CLI query + embedding | Top-3 | Read-only |
| Skills | Hermes CLI query + embedding | Top-3 | Read-only |

KAFED only manages RAG + Wiki. Memory, Sessions, and Skills are Agent-managed — KAFED queries them in read-only mode and includes the query embedding vector so the Agent can do its own matching.

#### EVAL Scoring

Five-dimensional task assessment:

| Dimension | Scale | Description |
|-----------|-------|-------------|
| F1 — Scope | 1–3 | Single → Multi → Cross-domain |
| F2 — People | 1–3 | Self → Team → Organization |
| F3 — Freshness | 1–3 | Common → Research → Novel/Realtime |
| F4 — Risk | 1–3 | Read-only → Modify → Deploy |
| F5 — Token Cost | 1–3 | One sentence → Paragraph → Long doc |

Score = max(F1..F5). Tier 1 (score≤1), Tier 2 (score=2), Tier 3 (score=3). The Agent uses this to decide whether to split tasks or call `find_partners()`.

---

## 5. Finder: Model Matching

### 5.1 Router — `find_partners(briefs)`

The single entry point. Accepts N task descriptions, returns N ranked candidate lists.

**Dual-mode routing:**

| Mode | Trigger | Method |
|------|---------|--------|
| `fast_route` | < 3 online models | Direct Hermes config + llama-server discovery |
| `full_route` | ≥ 3 models | 3-vector aggregation |

**Three-vector aggregation (full_route):**

```
Input 1: Task embeddings (N × 384d)
        cosine similarity ← task ⊗ model capability vectors
Input 2: Model capability vectors (from Explorer scans)
        + context_boost ← ContextSpace dynamic buffer
Input 3: Real-time status vectors (from Heartbeat probes)
        + sta_score ← [online, TPS, load, latency]

Aggregate: score = w_cap × cosine + w_ctx × context_boost + w_sta × sta_score
           (w_cap=0.5, w_ctx=0.3, w_sta=0.2 — configurable)
```

Each dimension has its own refresh cycle and decay curve:

| Dimension | Source | Refresh | Decay |
|-----------|--------|---------|-------|
| Capability vectors | Explorer `scan_all()` | Daily cron | Full overwrite |
| Context buffer | ContextSpace | Per-query | FIFO (500 entries) |
| Status vectors | Heartbeat probes | Per-probe | Exponential freshness decay |

### 5.2 Explorer — Model Discovery

Single-source discovery from Hermes `config.yaml` (no CLI, no subprocess):

```
scan_all()
  ├─ _load_hermes_config()        # Direct file read
  ├─ _discover_model_roles()      # auxiliary/tts/stt/fallback → role tags
  ├─ for each provider:
  │    ├─ /v1/models API query (metadata enrichment)
  │    ├─ pricing.resolve()       # PricingTable (cache > builtin > default)
  │    └─ build_meta_description() → embedding text
  └─ update_vector_space()        # Write worker_vectors.pkl
```

**Local/cloud detection** via URL (not provider name):
- `localhost`, `127.0.0.1`, `::1` → local
- `192.168.x.x` → cloud (remote server)
- All others → cloud

**Dynamic PricingTable**: `~/.kafed/pricing_cache.json` → code defaults → conservative estimate ($5/$15 per 1M tokens). Covers 24 models across 6 providers with official pricing sources.

### 5.3 Heartbeat — Status Monitoring

Cron-driven (every 2 minutes), not a daemon:

```
cron tick → Heartbeat.tick()
  ├─ need_probe() → freshness check + exponential backoff
  ├─ probe: local = curl /health, cloud = TCP connect
  └─ StatusCache.save() → freshness decay applied
```

**Exponential freshness decay** — status values interpolate between fresh and neutral as time passes:

```
freshness = exp(-decay_rate × elapsed_s)
vector[i] = fresh_value × freshness + default × (1 - freshness)
```

A model not probed in 60s has `sta_score ≈ 0.35`, naturally sinking below fresh models without explicit eviction.

---

## 6. Backend: Learning Loop

### 6.1 Analyzer — Solidifier

Called after every Agent response:

```python
solidify(insight, domain="GENERAL", source="agent_turn")
  → ingest(text, target="kafed")
    → chunk_document() → quality filter → embed → ChromaDB
    → EventChecker.after_ingest() → E1-E5 flywheel
```

Metadata preserved per chunk: heading chain, quality score, character count, chunk index.

### 6.2 Session Audit

Called at session end. Compares Director intent vs execution outcome:

```
session_end_audit()
  → AuditEngine.audit(AuditInput)
    → Rule-based checks (5 default rules, extensible)
    → Actions: promote to wiki, correct embedding, suggest skill, update SOUL
```

Rules are registered via `AuditRule` dataclasses — no hardcoded if-else chains.

### 6.3 Knowledge Audit

Offline KB health check (weekly cron):

| Check | What | Cost |
|-------|------|------|
| domain_health | Empty/skewed/tiny domains | Metadata only |
| quality_scan | Noise, short entries (sample) | Sample reads |
| freshness | Entries >90 days without hits | Timestamp scan |
| consistency | Near-duplicates, naming conventions | Prefix matching |
| coverage | Total count adequacy | 3-line check |

---

## 7. Knowledge Layer

### 7.1 RAG Engine

```
RAGEngine.query(question, top_k, domain, soft=True)
  → VectorStore.search() → cosine similarity ranking
  → soft=True: multi-domain expansion when boundary confidence is low
  → Returns: [{content, score, metadata, domain, level, type}, ...]
```

### 7.2 ContextProvider

Pre-EVAL multi-source recall. All sources use the same bge-small embedding model:

```
ContextProvider.recall(query, hexagram_id, domain_hint)
  → get embedding(query)
  → RAG: VectorStore.search(top_k=8)
  → Wiki: VectorStore.search(top_k=4, where={domain: "WIKI"})
  → Agent sources: Hermes CLI session search
  → ContextBundle → sorted by score
```

### 7.3 Classification

Three-tier hierarchical: Domain (47 clusters) → Level (33) → Type (98).

All three use the same `Entity + Registry` architecture:
- Embedding-based centroid matching
- Soft boundary for ambiguous inputs (expand to multiple clusters when confidence gap < 0.10)
- MiniBatchKMeans with weekly centroid rebuild

### 7.4 Quality Filter

16 noise patterns filtered: HTML tags, ligature artifacts, table corruption, repetitive boilerplate, copyright notices.

Quality formula (domain-agnostic):
```
0.3 + structure×0.25 + entropy×0.20 + length×0.15 - repetition×0.10 - noise×0.10
```

### 7.5 Flywheel Events (E1–E5)

| Event | Trigger | Action |
|-------|---------|--------|
| E1 — Threshold | Domain count crosses milestone | Log + suggest |
| E2 — Drift | Centroid moves >5% | Recomputation signal |
| E3 — Growth | Domain grows >30% since last repack | Repack suggestion |
| E4 — Dedup | Similarity >0.95 | Merge candidates |
| E5 — Stale | No hits in 90 days | Archive suggestion |

### 7.6 Knowledge Packages (.kpak)

Zip archives containing:
- `manifest.json` — version, domain, entry count, embedding model
- `knowledge_units.jsonl` — content + metadata
- `centroid.npy` — domain centroid for structural alignment
- `seed_rules.yaml` — optional bootstrap rules

Export/import via CLI: `python -m kafed.kpak pack|unpack|list|info`

---

## 8. Scheduler & Compensation

### 8.1 Task Model

```python
@dataclass
class Task(ABC):
    id: str
    interval: timedelta
    last_run: datetime | None
    max_missed: int = 10

    @abstractmethod
    def execute(self) -> TaskResult: ...
    def compensate(self, missed_count: int) -> TaskResult: ...
```

### 8.2 WSL Compensation

WSL cannot guarantee cron execution (Windows host may sleep). Compensation triggers:

1. **Bootstrap** — checks all overdue tasks, runs compensation
2. **Session start** — lightweight overdue check
3. **Hermes cron tick** — normal scheduled execution
4. **Manual** — `kafed scheduler run --compensate`

Each task's `compensate()` method coalesces multiple missed cycles into a single run (e.g., weekly centroid rebuild that missed 2 weeks runs once).

### 8.3 Built-in Tasks

| Task | Interval | Purpose |
|------|----------|---------|
| `heartbeat` | 2min | Probe model health, update status cache |
| `centroid_flywheel` | 12h | Rebuild domain centroids |
| `explorer_scan` | 24h | Rediscover models, update vectors + pricing |
| `knowledge_audit` | 7d | KB health check (domain/quality/freshness) |
| `flywheel_daily` | 24h | Event check + centroid update |

---

## 9. Configuration System

### Priority Chain

```
Environment variables  >  kafed.yaml  >  Code defaults
```

### Key Properties

| Category | Properties |
|----------|-----------|
| Paths | `data_dir`, `chroma_path`, `vectors_path`, `status_cache_path` |
| Embedding | `embedding_model` (bge-small-en-v1.5), `embedding_dim` (384) |
| Chunking | `chunk_max_chars` (500) |
| Retrieval | `top_k_default` (5) |
| Flywheel | E1 thresholds, E2 drift min, E3 growth pct, E4 dedup threshold, E5 stale days |
| Finder | `fast_route_max_workers` (3), `finder_w_cap/ctx/sta` (0.5/0.3/0.2) |
| Heartbeat | base/max intervals (10s/120s local, 60s/600s cloud), freshness threshold (0.3) |

### Secrets

API keys managed via `KafedSecrets`, loaded from `.env` or environment variables. Never appear in logs, `show()`, or config files.

---

## 10. Knowledge Lifecycle

```
1. Ingestion
   └─ solidify() or batch_ingest_files() → chunk → embed → ChromaDB

2. Classification
   └─ Domain · Level · Type metadata (embedding-based, weekly centroid rebuild)

3. Retrieval
   └─ RAGEngine.query() + ContextProvider.recall() (soft boundary)

4. Quality
   └─ 16 noise patterns filtered, domain-agnostic scoring

5. Flywheel
   └─ E1-E5: threshold, drift, growth, dedup, staleness

6. Sharing
   └─ .kpak export/import (structure + centroids, no raw data)
```

---

*KAFED v3.0 · Knowledge Agent Framework · MIT License*
