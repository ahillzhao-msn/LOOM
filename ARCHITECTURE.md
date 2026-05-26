# KAFED Architecture

> Version 2.2.0 · Five-layer intelligent flywheel · Environment-adaptive bootstrap · 45 tests

---

## Table of Contents

1. [Design Philosophy](#1-design-philosophy)
2. [Layer Architecture](#2-layer-architecture)
3. [Data Flow](#3-data-flow)
4. [Component Details](#4-component-details)
5. [Cron Schedule](#5-cron-schedule)
6. [Bootstrap & Installation](#6-bootstrap--installation)
7. [Configuration System](#7-configuration-system)
8. [Knowledge Lifecycle](#8-knowledge-lifecycle)
9. [Testing & Quality](#9-testing--quality)

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

Dual-mode routing — the single entry point `find_partners(briefs)` accepts N task descriptions and returns N ranked candidate lists:

| Mode | Trigger | Method |
|------|---------|--------|
| `fast_route` | < 3 workers | Direct llama.cpp discovery + config scan |
| `full_route` | ≥ 3 workers | 3-vector aggregation: task ⊗ model ⊗ status |

**Three-vector aggregation** (the core routing logic):

```
sub_task_embeddings (N × 384d)
         │
    cosine similarity  ← task embedding ⊗ model capability vectors
         + context_boost  ← ContextSpace dynamic buffer (recent context)
         + sta_score      ← status_vector × [w_cap, w_ctx, w_sta]
         │
         ▼
    N × FindPartnersResult (each: top-k candidates sorted by aggregate score)
         │
         ▼ Director decision tree + three reflections — final selection
```

Each dimension has its own embedding space and refresh cycle:

| Dimension | Source | Refresh | Decay |
|-----------|--------|---------|-------|
| Capability (model vectors) | Explorer `scan_all()` → `update_vector_space()` | Daily (cron) | None (full overwrite) |
| Context (task history) | ContextSpace buffer | Per-query | FIFO (500 entries) |
| Status (online/TPS/load) | Heartbeat probes | Per-probe | Exponential freshness decay |

#### Registry (`finder/registry.py`)

**v2.2 redesign**: Registry is now a pure query layer over Explorer's vector space.

- `roster.yaml` **removed** — all model data lives in Explorer's `worker_vectors.pkl`
- `register()`, `report_success()`, `sync_roster()` removed
- `load()` → reads from `worker_vectors.pkl` (auto-triggers Explorer scan if empty)
- `verify_candidates()` → reads real-time status from `StatusCache` (zero network I/O)
- `get_status_vector()` → decorator for StatusCache access

The Registry no longer owns model data — it's a thin bridge between Explorer (who discovers) and Heartbeat (who monitors).

#### Explorer (`finder/explorer.py`)

**v2.2 redesign**: Single-source model discovery from Hermes config.yaml.

```
scan_all()
  │
  ├─ _load_hermes_config()        # Reads config.yaml directly (no CLI)
  ├─ _discover_model_roles()      # auxiliary/tts/stt/fallback → role tags
  ├─ for each provider:
  │    ├─ _get_model_names()      # models list + /v1/models fallback for llamacpp
  │    ├─ pricing.resolve()       # PricingTable (cache > builtin > default)
  │    └─ _query_provider_models_api()  # /v1/models metadata enrichment
  ├─ _add_unreferenced_models()   # Roles without provider entries
  └─ pricing.save()               # Persist discovered prices
```

Key design decisions:

| Decision | v2.1 (old) | v2.2 (new) |
|----------|-----------|-----------|
| Discovery channels | 3: llama + hermes CLI + cloud_models | 1: Hermes config.yaml only |
| Local/cloud detection | Hardcoded provider name check (`llamacpp`) | URL-based (`localhost/127.0.0.1` = local) |
| Role discovery | None (name-based tag heuristics) | Full Hermes config scan (auxiliary/tts/stt/fallback) |
| Pricing | Static module-level dicts | `PricingTable` with cache file + update API |
| Model metadata query | Per-provider /v1/models | Same, with llamacpp fallback |

##### Local/Cloud Detection

```
from kafed.finder.explorer import _is_local_url

_is_local_url("http://localhost:8000/v1")     → True
_is_local_url("http://127.0.0.1:11434")       → True
_is_local_url("https://api.deepseek.com")     → False
_is_local_url("http://192.168.1.100:8000")    → False
```

##### Role Discovery

Explorer walks all Hermes config sections to discover which roles each model serves:

| Config section | Example | Role tag |
|---------------|---------|----------|
| `model.default` | `deepseek-v4-flash` | `default` |
| `fallback_model.model` | `leader` | `fallback` |
| `auxiliary.vision.model` | `deepseek-v4-flash` | `vision` |
| `auxiliary.compression.model` | `worker_sm2` | `compression` |
| `auxiliary.title_generation.model` | `worker_md1` | `title_generation` |
| `auxiliary.session_search.model` | `worker_sm1` | `session_search` |
| `auxiliary.web_extract.model` | `worker_sm1` | `web_extract` |
| `tts.*.model / model_id` | `gpt-4o-mini-tts` | `tts` |
| `stt.*.model / model_id` | `base` | `stt` |

A model can serve multiple roles (e.g., `deepseek-v4-flash` = `default` + `vision`). Roles are stored as both `meta.roles` (list of dicts, full config) and `meta.role_tags` (comma-separated string for embedding filtering).

##### Dynamic PricingTable

`Explorer.PricingTable` replaces module-level static pricing dicts:

```
Priority chain:
  pricing_cache.json  >  _BUILTIN_PRICING (code fallback)  >  _DEFAULT_CLOUD_COST ($5/$15)

Cache file: ~/.kafed/pricing_cache.json (KAFED_PRICING_CACHE env to override)

Update API:
  pt = Explorer.PricingTable()    # auto-load from cache
  pt.set(provider, model, input, output)     # add/override
  pt.set_provider_default(provider, i, o)    # provider-level default
  pt.remove(provider, model)                 # revert to builtin
  pt.save()                                  # persist to cache
```

Each `Explorer.scan_all()` call loads pricing from cache at start and saves at end.
Unknown cloud models default to $5/$15 per 1M tokens (conservative — overestimates to prevent under-cost routing).

##### Model Metadata Schema (`finder/matcher.py`)

```
MODEL_META_SCHEMA = {
    # Identity
    "name": (str, ""), "provider": (str, "local"), "model_id": (str, ""),
    # Capacity
    "context_window": (int, 16384), "max_tokens": (int, 0),
    # Generation defaults
    "temperature": (float, 0.6), "top_p": (float, 0.9),
    "top_k": (int, 40), "repeat_penalty": (float, 1.1),
    # Capabilities
    "supports_reasoning": (bool, False), "supports_vision": (bool, False),
    "supports_functions": (bool, False), "supports_streaming": (bool, True),
    "supports_json_mode": (bool, False),
    # Performance & Cost ($/1M tokens)
    "tps": (int, 0),
    "cost_per_input_token": (float, 0.0),   # $/1M input tokens
    "cost_per_output_token": (float, 0.0),  # $/1M output tokens
    # Knowledge
    "knowledge_cutoff": (str, ""),
    # Role tags
    "role_tags": (str, ""),        # comma-separated for embedding filtering
    "provider_type": (str, "cloud"),  # local / cloud / on-prem
    # Status
    "is_online": (bool, True),
}
```

All matching, filtering, and sorting happens in embedding space — no field-by-field hardcoded comparisons. New schema fields automatically participate through `build_meta_description()` which generates the embedding text.

#### Heartbeat (`finder/heartbeat.py`)

The Heartbeat is not a daemon — it's a cron-driven probe cycle:

```
cron (every 2min) → run_tick()
  ├─ Heartbeat.tick()
  │    ├─ registry.load() → worker_names
  │    ├─ for each name:
  │    │    ├─ need_probe() → check freshness + next_probe_at + force_probe
  │    │    └─ _probe_one(name, provider) → StatusEntry
  │    └─ cache.save()
  └─ force_probe(name) — sync call from Router
```

Two probe modes:

| Mode | Health check | TPS | Latency |
|------|-------------|-----|---------|
| Local (llama-server) | `curl /health` | Short /v1/completions | RTT |
| Cloud (API) | TCP connect to base_url | Historical estimate | RTT |

**Forgetting Curve** — `status_vector` property in `StatusEntry` does not return a raw snapshot. It interpolates between fresh values and neutral defaults based on exponential freshness decay:

```python
freshness = exp(-decay_rate × elapsed_s)    # 1.0 = just probed, 0.0 = stale
vector[i] = fresh_value × freshness + stale_default × (1 - freshness)
```

| Dimension | Fresh value | Stale default (uncertain) |
|-----------|------------|--------------------------|
| online | 1.0 / 0.0 | 0.5 (unknown) |
| tps_norm | min(1.0, tps/200) | 0.0 (no assumption) |
| load | actual 0.0–1.0 | 0.5 (unknown) |
| latency_ms | actual ms | 1000ms (pessimistic) |

Result: a model that hasn't been probed in 60s has `sta_score ≈ 0.35` in routing, causing it to naturally sink below freshly probed models — without explicit eviction logic.

**Backoff scheduling** uses exponential backoff with change detection:

```python
delay = base × 2^backoff_level  # cap at max
# base = 10s (local) or 60s (cloud)
# max = 120s (local) or 600s (cloud)
```

State unchanged → `backoff_level++` → probe less frequently.
State changed → `backoff_level = 0` → probe again soon.

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
3. **LLM task** — natural language → `delegate_to_subagent()` generates Hermes-format params:
   ```python
   {"model": "deepseek-v4-flash",
    "provider": "deepseek",
    "params": {"temperature": 0.0, "top_p": 0.9}}
   ```
   The Dispatcher does not call models directly — it produces parameters in Hermes' standard format. The Agent (LLM) calls `delegate_task()` with these params.

`dispatch_for()` bridges Finder → Executor: it takes the model selected by `find_partners()` and generates a complete Hermes delegate_task config with generation parameters from the model's metadata schema.

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

#### ContextProvider (`knowledge/context/context_provider.py`)

Pre-EVAL knowledge recall — all sources use **embedding matching** (no keyword extraction):

| Source | Match method | KAFED role |
|--------|-------------|-----------|
| RAG (Chroma) | Embedding cosine similarity | Primary recall channel |
| Wiki | Embedding cosine similarity (domain filter) | Same store, domain-tagged |
| Memory | Hermes CLI query + embedding | Read-only, Agent-managed |
| Sessions | Hermes CLI query + embedding | Read-only, Agent-managed |
| Skills | Hermes CLI query + embedding | Read-only, Agent-managed |

The query embedding vector is included in the ContextBundle so the calling Agent can do its own embedding matching against Memory/Session/Skill stores that only the Agent can access.

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

## 5. Cron Schedule

Three KAFED-managed cron jobs (registered by bootstrap):

| Job | Schedule | What it does | Depends on |
|-----|----------|-------------|------------|
| `kafed-heartbeat` | `*/2 * * * *` | Probes model health, updates status_cache.pkl with freshness decay | Hermes cron (any OS) |
| `kafed-explorer` | `0 4 * * *` | Discovers models from Hermes config, updates worker_vectors.pkl + pricing_cache.json | Hermes cron (any OS) |
| `kafed-centroids` | `0 3 * * 0` | Rebuilds knowledge domain centroids | Hermes cron, data present |
| `kafed-pulse` (WSL) | `*/15 * * * *` | Conditional task scheduler — checks all registered tasks, runs due ones | WSL + Hermes cron |

All cron jobs use `no_agent` mode (script stdout delivered directly), consuming zero LLM tokens.

### Refresh Cycle Architecture

```
                   Explorer (daily 4am)
                   ┌──────────────────────────┐
                   │  Hermes config → models   │
                   │  Pricing cache → costs     │
                   │  /v1/models → metadata     │
                   └────────┬─────────────────┘
                            │ worker_vectors.pkl (full overwrite)
                            ▼
                   Router._vectors (loaded on demand)

                   Heartbeat (every 2min)
                   ┌──────────────────────────┐
                   │  need_probe() → probe     │
                   │  freshness decay apply     │
                   │  status_vector updated     │
                   └────────┬─────────────────┘
                            │ status_cache.pkl (per-entry update)
                            ▼
                   Registry.verify_candidates (zero I/O)
```

---

## 6. Bootstrap & Installation

### One-Command Install

```bash
bash scripts/kafed-bootstrap.sh
# or: pip install -e . && kafed-bootstrap
```

### Bootstrap Phases

| Phase | What happens | Auto-detects |
|-------|-------------|-------------|
| 1: Environment | Hermes venv, WSL, GPU, llama-server, providers | All passive scans |
| 2: Config | Generate `~/.kafed/kafed.yaml` with detected values | llama URL, GPU, provider list |
| 3: Data init | Create dirs + initialize ChromaDB + Explorer vectors + centroids | Embedding model auto-download |
| 4: Cron | Register heartbeat (2min) + explorer (4am) + centroids (weekly) + pulse (WSL) | Hermes available |
| 5: Install | `pip install -e .` into Hermes venv (default) or standalone | Hermes venv path |

### Default Install Target

KAFED prefers installing **into Hermes' existing venv** (`$HERMES_HOME/.venv`) to avoid duplicate dependency overhead. Falls back to standalone `.venv` only when Hermes is not detected. This is determined by the bootstrap at install time, not a compile-time flag.

---

## 7. Configuration System

### Priority Chain

```
Environment variables  >  kafed.yaml  >  Code defaults
```

### Config Properties (`config.py`)

| Category | Key Properties |
|----------|----------------|
| Paths | `data_dir`, `chroma_path`, `vectors_path`, `backlog_data`, `status_cache_path` |
| Filenames | `centroids_filename`, `labels_filename`, `event_state_filename` |
| Embedding | `embedding_model` (bge-small-en-v1.5), `embedding_dim` (384) |
| Chunking | `chunk_max_chars` (500), `chunk_overlap` (50) |
| Retrieval | `top_k_default` (5) |
| Flywheel | `e1_thresholds`, `e2_drift_min`, `e3_repack_growth_pct`, `e4_dedup_threshold`, `e5_stale_days` |
| Finder | `fast_route_max_workers` (3), `finder_w_cap/ctx/sta` (0.5/0.3/0.2) |
| llama-server | `llama_base_url` (env: `KAFED_LLAMA_BASE_URL`, yaml: `llama_server.base_url`) |
| Heartbeat | `heartbeat_base_local/cloud`, `heartbeat_max_local/cloud`, `freshness_threshold` |
| Server | `host` (0.0.0.0), `port` (8765 — legacy) |
| Cloud | `cloud_models` — pre-registered model definitions with real pricing |
| Pricing cache | `~/.kafed/pricing_cache.json` (env: `KAFED_PRICING_CACHE`) |
| Roster | `roster_path` — **deprecated** (kept for backward compat, not written) |

### Secrets (`KafedSecrets`)

API keys are managed separately via `KafedSecrets`:
- Loaded from `.env` or environment variables
- Never appear in logs, `show()`, or config files
- Accessed via typed properties: `secrets.deepseek_api_key`, `secrets.openai_api_key`

---

## 8. Knowledge Lifecycle

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

## 9. Testing & Quality

### Test Suite

45 tests across 7 test files covering:
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

*KAFED — Knowledge Agent Framework for Embedded Data · v2.2.0 · MIT License*
