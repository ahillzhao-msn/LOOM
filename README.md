# KAFED — Knowledge Agent Framework for Embedded Data

> **Five-layer intelligent flywheel · Zero-hardcoded configuration · Privacy-first RAG**
>
> A self-organizing knowledge engine: ingest → classify → retrieve → decide → execute → absorb.

<p align="center">
  <img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-yellow.svg">
  <img alt="Python 3.10+" src="https://img.shields.io/badge/Python-3.10+-blue.svg">
  <img alt="Chunks" src="https://img.shields.io/badge/Chunks-93K+-green.svg">
  <img alt="Domains" src="https://img.shields.io/badge/Domains-38-purple.svg">
  <img alt="Version" src="https://img.shields.io/badge/Version-2.2.0-red.svg">
</p>

---

## What Is KAFED

KAFED is a **knowledge management engine** designed for AI agents that need to own, organize, and evolve their knowledge — not just query it.

Unlike a standard RAG pipeline that only retrieves, KAFED **classifies, evaluates, routes, executes, and absorbs** — forming a complete flywheel that gets smarter with every interaction.

### Architecture (5 layers)

```
                  ┌─────────────────────────┐
    User Input →  │  D — Director           │  Strategic planning, EVAL, decision tree
                  │  (eval · decision ·      │
                  │   strategy · pipeline)   │
                  └───────────┬─────────────┘
                              │ subtask list
                              ▼
                  ┌─────────────────────────┐
                  │  F — Finder             │  Model discovery, 3-vector routing
                  │  (router · registry ·    │
                  │   explorer · heartbeat)  │
                  └───────────┬─────────────┘
                              │ matched models
                              ▼
                  ┌─────────────────────────┐
                  │  E — Executor           │  DAG scheduling, dispatch, feedback loop
                  │  (dag · dispatcher ·     │
                  │   engine)               │
                  └───────────┬─────────────┘
                              │ results
                              ▼
                  ┌─────────────────────────┐
                  │  A — Analyzer           │  Pulse scheduling, audit, KB inspection
                  │  (pulse · audit ·        │
                  │   kb_audit)             │
                  └───────────┬─────────────┘
                              │ insights
                              ▼
                  ┌─────────────────────────┐
                  │  K — Knowledge          │  Vector store, RAG, classification, events
                  │  (rag · classify ·       │
                  │   quality · flywheel)    │
                  └───────────┬─────────────┘
                              │
                  ◄───── flywheel loop ──────►
```

Each layer is a gear in a closed loop. Data cycles through D→F→E→A→K→D, and the system evolves without external intervention.

---

## Why KAFED

### The Problem

Standard RAG pipelines are **passive**: they store documents, retrieve chunks, and stop there. They don't:
- Classify knowledge by domain or type
- Evaluate task complexity before routing
- Self-audit knowledge freshness and quality
- Evolve their structure over time

### The Solution

KAFED treats knowledge as a **living system**. The 5-layer flywheel provides:

| Layer | What It Solves |
|-------|----------------|
| **D** — Director | "How complex is this task? Should I decompose it?" |
| **F** — Finder | "Which model or tool is best suited for this sub-task?" |
| **E** — Executor | "How do I run N dependent subtasks in parallel?" |
| **A** — Analyzer | "Did the result produce new knowledge? Any patterns?" |
| **K** — Knowledge | "Store it, classify it, and check if we need to reorganize." |

---

## Quick Start

### One-command install (recommended)

```bash
# Clone
git clone https://github.com/ahillzhao-msn/KAFED.git
cd KAFED

# One-command bootstrap — detects environment, generates config, inits modules, installs cron
bash scripts/kafed-bootstrap.sh

# Or if KAFED is already pip-installed:
kafed-bootstrap
```

The bootstrap auto-detects:
- **Hermes** venv — installs directly into it (no duplicate deps)
- **WSL** — deploys pulse-manager for conditional cron execution
- **GPU** — enables CUDA embedding acceleration
- **llama-server** — auto-discovers base URL and port
- **Existing Hermes providers** — auto-generates cloud model list

After bootstrap, verify:

```bash
# Check configuration
python3 -c "from kafed.config import get_config; print(get_config().show())"

# Start heartbeat (cron registered automatically)
kafed-heartbeat

# Scan available models
kafed-explore
```

### Manual install

```bash
# Install into Hermes venv (preferred)
hermes venv python3 -m pip install -e .

# Or standalone venv
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Generate config (auto-adapts to environment)
python3 -m kafed.install.bootstrap --auto

# Or manually copy and edit
cp kafed.yaml.example ~/.kafed/kafed.yaml
cp .env.example ~/.kafed/.env
```

### What gets initialized

| Component | What happens | Trigger |
|-----------|-------------|---------|
| **Config** | Environment-adapted `~/.kafed/kafed.yaml` | Bootstrap Phase 2 |
| **Directories** | `data/chroma`, `feedback_logs`, `kpak`, logs | Bootstrap Phase 3 |
| **ChromaDB** | PersistentClient + collection creation | Bootstrap Phase 3 |
| **Explorer** | `llama-server` + `hermes config` + cloud model scan | Bootstrap Phase 3 |
| **Vector space** | Embedding-based worker vectors | Bootstrap Phase 3 |
| **Heartbeat cron** | Every 2min model status probing | Bootstrap Phase 4 |
| **Explorer cron** | Daily 4am model vector + pricing refresh | Bootstrap Phase 4 |
| **Centroid rebuild** | Weekly Sunday 3am | Bootstrap Phase 4 |
| **Pulse (WSL)** | 15min conditional task scheduler | Bootstrap Phase 4 |

### Basic Usage

```python
from kafed.entry import recall, solidify

# Ingest knowledge into the vector store
result = solidify(
    "SAP PM notification uses transaction IW21 for creation.",
    target="kafed",
    domain="SAP_PM",
    source="training_manual",
)
# → {"status": "ok", "target": "kafed", "entries": 3}

# Retrieve relevant knowledge
results = recall(
    "How to create a PM notification?",
    top_k=5,
    soft=True,
)
for r in results:
    print(f"[{r['domain']}] {r['content'][:100]}...")
```

### Pipeline Orchestration

```python
from kafed.director.pipeline import SOUL_CORE, PipelineRunner

runner = PipelineRunner(SOUL_CORE)
while True:
    step = runner.next_step()
    if not step:
        break
    # LLM executes the step freely
    runner.complete(step.step_id, result="done")
```

### Knowledge Packages (.kpak)

```bash
# List available packages
python -m kafed.kpak list

# Export a domain
python -m kafed.kpak pack SAP_PM

# Import from another instance
python -m kafed.kpak unpack ./SAP_PM.kpak

# Inspect a package
python -m kafed.kpak info ./SAP_PM.kpak
```

---

## Configuration

KAFED uses a single configuration hub (`kafed/config.py`) with a clear priority chain:

```
Environment variables  >  YAML file (kafed.yaml)  >  Code defaults
```

```python
from kafed.config import get_config, get_secrets

cfg = get_config()
cfg.show()                     # View all config (keys masked)

secrets = get_secrets()
secrets.deepseek_api_key       # From .env or environment variable
```

All paths, thresholds, and weights are parameterized via config properties. No hardcoded values in sub-modules.

---

## Project Layout

```
KAFED/
├── src/kafed/
│   ├── config.py           — Global configuration hub
│   ├── log.py              — Unified logging (file + console)
│   ├── entry.py            — Pipeline bridge layer
│   ├── backlog.py          — Cross-session task queue
│   ├── director/           — Strategic decisions (7 modules)
│   │   ├── eval.py         — EVAL 5-dimension scoring
│   │   ├── decision.py     — Autonomous decision tree
│   │   ├── strategy.py     — Strategic orientation
│   │   ├── planner.py      — Task decomposition
│   │   ├── pipeline.py     — Pipeline commitment chain
│   │   └── protocol.py     — Inter-layer protocols
│   ├── finder/             — Model discovery & routing (6 modules)
│   ├── executor/           — DAG execution (3 modules)
│   ├── analyzer/           — Pulse & audit (4 modules)
│   ├── knowledge/          — RAG, classification, quality (12 modules)
│   │   ├── rag/            — Vector store, chunker, embedding
│   │   ├── classify/       — Embedding-based domain classification
│   │   ├── quality/        — Document quality scoring
│   │   └── flywheel/       — Event-driven self-check (E1-E5)
│   ├── kpak/               — Knowledge package export/import
│   ├── install/            — Bootstrap & environment detection
│   └── client/             — CLI + FlowVisualizer
├── scripts/                — Utility scripts + bootstrap
├── tests/                  — pytest suite (45 tests)
├── templates/              — SOUL cognitive architecture templates
├── kafed.yaml.example      — Configuration template
├── .env.example            — Secrets template
├── setup.sh                — One-click install
├── ARCHITECTURE.md         — Full architecture documentation
└── README.md
```

---

## Dependencies

- **Python 3.10+**
- **ChromaDB** — vector database
- **sentence-transformers** — bge-small-en-v1.5 embedding model
- **NumPy**, **PyYAML** — core
- **PyTorch** (optional) — GPU-accelerated embedding

---

## Core Principles

1. **Vector store is primary storage** — not an accessory, the physical kernel of knowledge
2. **Centroid is internalized structure** — store mathematical structure, not raw weights
3. **RAG is instantly available** — ingest and retrieve immediately, no SFT/training needed
4. **Event-driven, not threshold-driven** — self-checking flywheel (E1-E5), no hardcoded timers
5. **Share structure, not weights** — `.kpak` shares centroids, not model weights
6. **Quality first, don't over-engineer** — slow but clean

---

## Related Projects

- [YiCeNet](https://github.com/ahillzhao-msn/YiCeNet) — I-Ching inspired neural network, the intuition layer for KAFED pipelines

---

## License

[MIT](LICENSE) © ahillzhao-msn
