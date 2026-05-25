# KAFED Architecture

> Version 2.1.0 · Five-layer intelligent flywheel · 93K+ chunks · 38 domains

---

## Table of Contents

1. [Design Philosophy](#1-design-philosophy)
2. [Layer Architecture](#2-layer-architecture)
3. [Data Flow](#3-data-flow)
4. [Component Details](#4-component-details)
5. [Configuration System](#5-configuration-system)
6. [Knowledge Lifecycle](#6-knowledge-lifecycle)
7. [Testing & Quality](#7-testing--quality)

---

## 1. Design Philosophy

KAFED is built on a three-level framework inspired by classical Chinese philosophy:

| Level | Principle | Engineering Manifestation |
|-------|-----------|--------------------------|
| **道** (Tao) | Follow nature, do not overreach | Pipeline commitment chain, not rigid scripts |
| **法** (Method) | Rules and systems | EVAL scoring, decision tree, four reflections |
| **兵** (Tactics) | Win first, then fight | Read before act, one-step-one-verify |

### Six Engineering Principles

1. **Vector store is primary storage** — not an accessory bolted onto the side. Everything revolves around the vector database.
2. **Centroid is internalized structure** — store mathematical cluster representations, not raw weights or raw text.
3. **RAG is instantly available** — ingest and retrieve immediately. No SFT, no training pipeline, no delay.
4. **Event-driven, not threshold-driven** — the self-checking flywheel (E1–E5) responds to change events, not hardcoded timers.
5. **Share structure, not weights** — `.kpak` packages share centroid vectors and knowledge units, not model weights.
6. **Quality first, don't over-engineer** — prefer a clean 100-line solution over a sophisticated 1000-line one.

---

## 2. Layer Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                         D — Director                               │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐           │
│  │  EVAL    │  │ Decision │  │Strategy  │  │Pipeline  │           │
│  │ (5-dim)  │  │ Tree     │  │Selector  │  │Runner    │           │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘           │
│  Core: Task complexity assessment, autonomous decision-making,     │
│        strategic orientation selection, pipeline step tracking.    │
├────────────────────────────────────────────────────────────────────┤
│                         F — Finder                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐           │
│  │ Registry │  │ Router   │  │ Explorer │  │ Heartbeat│           │
│  │ (roster) │  │ 3-vector │  │ (scan)   │  │ (health) │           │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘           │
│  Core: Dual-mode model discovery (fast/full), context-aware        │
│        embedding-space routing, status monitoring.                 │
├────────────────────────────────────────────────────────────────────┤
│                         E — Executor                               │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                          │
│  │ DAG      │  │Dispatcher│  │ Engine   │                          │
│  │Scheduler │  │ (script+ │  │(feedback │                          │
│  │          │  │  LLM)    │  │  loop)   │                          │
│  └──────────┘  └──────────┘  └──────────┘                          │
│  Core: DAG dependency management, supervised feedback loop         │
│  (fail → replan → continue or abort).                             │
├────────────────────────────────────────────────────────────────────┤
│                         A — Analyzer                               │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                          │
│  │ Pulse    │  │ Audit    │  │ KB Audit │                          │
│  │Scheduler │  │Engine    │  │Inspector │                          │
│  └──────────┘  └──────────┘  └──────────┘                          │
│  Core: Task scheduling, session audit (intent vs outcome),         │
│        knowledge base health inspection.                           │
├────────────────────────────────────────────────────────────────────┤
│                         K — Knowledge                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐           │
│  │ RAG      │  │ Classify │  │ Quality  │  │ Flywheel │           │
│  │(engine)  │  │(domains) │  │(clean)   │  │(E1-E5)   │           │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘           │
│  Core: Vector retrieval, 3-tier hierarchical classification        │
│  (Domain → Level → Type), quality filtering, event-driven flywheel.│
└────────────────────────────────────────────────────────────────────┘
```

---

## 3. Data Flow

### Normal Path (Task Execution)

```
1. Input → D: EVAL (F1-F5 scoring) → decision tree → strategy selection
2. D → F: subtask list → find_partners() → model candidates per subtask
3. F → D: [subtask → model candidates] ranked by embedding similarity
4. D → E: TaskPlan with selected models → ExecutorEngine.execute_dag()
5. E → A: ExecutionReport → Analyzer.absorb() (pattern detection, insight extraction)
6. A → K: KnowledgeDeposit → vector store write + flywheel events
```

### Supervised Feedback Loop

```
Executor runs DAG. Each task completion/failure triggers callback:
  - First failure → REPLAN (Director re-evaluates and adjusts)
  - Subsequent failures → CONTINUE (don't let one task block the whole DAG)
  - Any failure point can trigger ABORT (Director decides to abort)
```

### Knowledge Flywheel (E1-E5)

```
E1: Threshold — domain entry count crosses pre-defined thresholds (10, 50, 100...)
E2: Drift — centroid drift exceeds minimum (0.05)
E3: Growth — domain grows >30% since last repack
E4: Dedup — similarity check finds >0.95 duplicate candidates
E5: Stale — entries older than 90 days without hits
```

---

## 4. Component Details

### 4.1 Director Layer

#### EVAL (`director/eval.py`)

Five-dimensional task assessment:

| Dimension | Scale | Description |
|-----------|-------|-------------|
| F1 — Scope | 1–3 | Single point → Multi → Cross-domain |
| F2 — People | 1–3 | Self → Team → Organization |
| F3 — Freshness | 1–3 | Common → Requires research → Novel/Real-time |
| F4 — Risk | 1–3 | Read-only → Modify → Deploy |
| F5 — Token Cost | 1–3 | One sentence → Paragraph → Long document |

Score = max(F1..F5). Tier 1 (score≤1) → quick path. Tier 3 (score≥3) → full DAG.

#### Decision Tree (`director/decision.py`)

```
Goal alignment check → Irreversibility check → Cost check → Precedent check
→ Each returns: EXECUTE_DIRECT / PROPOSE_SCHEDULE / PROPOSE_DISCUSS / DEFER / ESCALATE / DELEGATE
```

#### Pipeline Runner (`director/pipeline.py`)

Three pre-defined pipelines:

| Pipeline | Steps | Use Case |
|----------|-------|----------|
| `soul_core` | 問→卦→召→評→界→決→編?→應→固 | General purpose |
| `soul_quick` | 問→卦→召→評→應→固 | Simple tasks (Tier 1) |
| `soul_deep` | 問→卦→召→評→界→決→編→應→固 | Cross-domain (Tier 3) |

The runner tracks step status (pending/running/done/skipped/blocked) and enforces dependency order. Steps are not scripts — they are checklists that the LLM executes freely.

### 4.2 Finder Layer

#### Router (`finder/router.py`)

Dual-mode routing:

| Mode | Trigger | Method |
|------|---------|--------|
| `fast_route` | < 3 workers | Direct llama.cpp discovery + config scan |
| `full_route` | ≥ 3 workers | 3-vector aggregation: task ⊗ model ⊗ status |

#### Registry (`finder/registry.py`)

Manages `roster.yaml` — the canonical model pool. Loads from:
1. `roster.yaml` (if exists)
2. `config.yaml` (Hermes config, if roster missing)
3. `cloud_models` (from config.py, always included)

#### Explorer (`finder/explorer.py`)

Scans all model sources:
1. `llama-server /v1/models` — local models with full metadata
2. `config.yaml` — Hermes provider models
3. `roster.yaml` / `cloud_models` — pre-registered + cloud models

### 4.3 Executor Layer

#### DAG Scheduler (`executor/dag.py`)

State machine: `Pending → Ready → Running → Completed / Failed`
- Automatic retry (1 attempt)
- Blocked propagation (dependency failure → downstream blocked)
- Max concurrent tasks: configurable (default 3)

#### Dispatcher (`executor/dispatcher.py`)

Three execution modes:
1. **Script** — `sh:` prefix → subprocess shell
2. **Function** — `fn:` prefix → Python callable
3. **LLM task** — natural language → `dispatch_for()` generates delegate_task params

#### Engine (`executor/engine.py`)

Orchestrates DAG execution with the feedback loop. `execute_dag()` takes:
- `tasks: list[DAGTask]` — task nodes with dependencies
- `feedback_callback: (task_id, status, result) → FeedbackDecision`
- Returns `ExecutionReport` with per-task results and summary

### 4.4 Analyzer Layer

#### Pulse (`analyzer/pulse.py`)

Task scheduling engine. Remembers last_run per task, checks if any are due. Runs asynchronously (not a daemon — WSL limitation). High-priority tasks execute immediately; low-priority ones write trigger files.

#### Audit (`analyzer/audit.py`)

Session-level quality auditing. Compares director intent vs execution outcome. Detects patterns (repeated failures, scope creep, etc.). Produces actionable recommendations.

#### KB Audit (`analyzer/kb_audit.py`)

Knowledge base health checks:
- Domain health — centroid drift, entry distribution
- Quality scoring — noise patterns, format violations
- Freshness — stale entry detection
- Consistency — cross-domain classification conflicts
- Coverage — domain gaps and overlaps

### 4.5 Knowledge Layer

#### RAG Engine (`knowledge/rag/rag_engine.py`)

`query(text, top_k, domain, soft)` → ranked results
- `soft=True` enables cross-domain expansion when boundary confidence is low
- Results include metadata: domain, level, type, source, confidence

#### Classification (`knowledge/classify/`)

Three-tier hierarchical classifier:

```
Domain (38 clusters) → Level (32, e.g. L1=Language, L4=Company-specific)
→ Type (98, e.g. declarative, procedural, reasoning, experiential)
```

All three tiers use the same `Entity + Registry` architecture:
- Embedding-based centroid matching
- Soft boundary for ambiguous inputs
- K-means with weekly centroid rebuild

#### Quality (`knowledge/quality/quality.py`)

16 noise patterns filtered: HTML tags, ligature artifacts, table corruption, repetitive boilerplate, copyright notices, etc.

#### Flywheel Events (`knowledge/flywheel/event_checker.py`)

| Event | Trigger | Action |
|-------|---------|--------|
| E1 — Threshold | Domain count crosses milestone | Log, suggest action |
| E2 — Drift | Centroid moves >5% | Recomputation signal |
| E3 — Growth | Domain grows >30% | Repack suggestion |
| E4 — Dedup | Similarity >0.95 | Merge candidates |
| E5 — Stale | No hits in 90 days | Archive suggestion |

---

## 5. Configuration System

### Priority Chain

```
Environment variables  >  kafed.yaml  >  Code defaults
```

### Config Properties (`config.py`)

| Category | Key Properties |
|----------|----------------|
| Paths | `data_dir`, `chroma_path`, `roster_path`, `vectors_path`, `backlog_data` |
| Filenames | `centroids_filename`, `labels_filename`, `event_state_filename` |
| Embedding | `embedding_model` (bge-small-en-v1.5), `embedding_dim` (384) |
| Chunking | `chunk_max_chars` (500), `chunk_overlap` (50) |
| Retrieval | `top_k_default` (5) |
| Flywheel | `e1_thresholds`, `e2_drift_min`, `e3_repack_growth_pct`, `e4_dedup_threshold`, `e5_stale_days` |
| Finder | `fast_route_max_workers` (3), `finder_w_cap/ctx/sta` (0.5/0.3/0.2) |
| Heartbeat | `heartbeat_base_local/cloud`, `heartbeat_max_local/cloud`, `freshness_threshold` |
| Server | `host` (0.0.0.0), `port` (8765 — legacy) |
| Cloud | `cloud_models` — pre-registered model definitions |

### Secrets (`KafedSecrets`)

API keys are managed separately via `KafedSecrets`:
- Loaded from `.env` or environment variables
- Never appear in logs, `show()`, or config files
- Accessed via typed properties: `secrets.deepseek_api_key`, `secrets.openai_api_key`

---

## 6. Knowledge Lifecycle

```
1. Ingestion
   └── PDF/DOCX/HTML → chunker → embedding → ChromaDB
2. Classification
   └── Domain · Level · Type metadata added (embedding-based)
3. Retrieval
   └── RAGEngine.query() → ranked results with soft boundary
4. Quality Check
   └── Clean text, score quality, filter noise
5. Flywheel Events
   └── E1-E5: threshold, drift, growth, dedup, stale
6. Knowledge Package
   └── .kpak export/import for cross-instance sharing
```

### Cross-Instance Knowledge Sharing

KAFED supports knowledge sharing via `.kpak` files — zip archives containing:
- `manifest.json` — version, domain, entry count, embedding model
- `knowledge_units.jsonl` — content + metadata per entry
- `centroid.npy` — optional domain centroid for structural alignment
- `seed_rules.yaml` — optional bootstrap rules

Export: `python -m kafed.kpak pack <domain>`
Import: `python -m kafed.kpak unpack <domain.kpak>`

---

## 7. Testing & Quality

### Test Suite

36 tests across 7 test files covering:
- Pipeline orchestration (DAG scheduler, step tracking)
- Knowledge operations (chunking, quality filtering, classification integration)
- RAG engine (end-to-end retrieval validation)
- Audit engine (intent vs outcome comparison)

### Per-Step Quality Gates

Each software change follows:
1. **Syntax check** — auto-run on file write
2. **Import verification** — all cross-module imports valid
3. **Test suite** — full pytest run before commit
4. **Sensitive data scan** — no personal paths, emails, or API keys

---

*KAFED — Knowledge Agent Framework for Embedded Data · v2.1.0 · MIT License*
