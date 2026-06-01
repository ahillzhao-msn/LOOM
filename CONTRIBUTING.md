# Contributing to LOOM

Thank you for your interest in LOOM — a conversation-level knowledge management engine for AI agents.

This document covers the practical guidelines for contributing code, documentation, and ideas.

---

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Architecture Overview](#architecture-overview)
- [Coding Standards](#coding-standards)
- [Testing](#testing)
- [Pull Request Workflow](#pull-request-workflow)
- [Commit Guidelines](#commit-guidelines)
- [Documentation](#documentation)
- [Feature Requests & Bug Reports](#feature-requests--bug-reports)

---

## Code of Conduct

This project follows a simple principle: **诚·直 (Sincerity · Directness).**

- Be honest about what works and what doesn't.
- Respect that this project is a living cognitive architecture — propose changes with evidence, not opinion.
- Assume good faith. The goal is a better LOOM, not a larger ego.

---

## Getting Started

### Prerequisites

- Python 3.10+
- A local ChromaDB (auto-installed with pip)
- Optional: CUDA-compatible GPU for embedding acceleration

### Development Setup

```bash
git clone https://github.com/ahillzhao-msn/LOOM.git
cd LOOM

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install in editable mode with dev dependencies
pip install -e ".[dev]"

# Verify installation
python3 -c "import loom; print(loom.__version__)"

# Run the test suite
python3 -m pytest tests/
```

### Hermes Integration (Optional)

If you use LOOM with [Hermes Agent](https://github.com/NousResearch/hermes-agent):

```bash
# Symlink the Hermes tool bridge
bash scripts/install/symlink-tools.sh

# Or install lifecycle hooks for zero-touch integration
bash scripts/install/install-loom-hooks.sh
```

---

## Architecture Overview

LOOM has three conceptual layers:

```
┌── Loom Conversation (logical lifecycle) ──────────────┐
│                                                        │
│  ┌── Frontend (per-turn) ──┐   ┌── Backend (async) ─┐ │
│  │  Director.recommend()   │──►│  Analyzer.solidify()│ │
│  │  Finder.find_partners() │   │  Scheduler          │ │
│  │  Knowledge (RAG)        │◄──│  Flywheel (E1-E5)   │ │
│  └──────────────────────────┘   └────────────────────┘ │
│                                                        │
│  Conversation → Session → Turn (three-tier lifecycle)  │
└────────────────────────────────────────────────────────┘
```

Key design principles:

1. **Agent owns decisions, LOOM provides context** — the engine enriches, never replaces, the agent's judgment.
2. **Embedding space is the universal language** — classification, retrieval, and model matching all happen in vector space.
3. **Quality over quantity** — every chunk is scored. Noise is filtered before storage, not during retrieval.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full technical design.

---

## Coding Standards

### Python

- **Formatter**: [Black](https://github.com/psf/black) — run `black src/ tests/` before committing.
- **Import sorting**: [isort](https://github.com/PyCQA/isort) — run `isort src/ tests/`.
- **Type hints**: Required for all public functions. Use `from __future__ import annotations` for forward references.
- **PEP 8**: Follow it unless Black overrides a specific rule.
- **Line length**: 100 characters (Black default).

### Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| Modules | `snake_case` | `vector_store.py` |
| Classes | `PascalCase` | `VectorStore` |
| Functions | `snake_case` | `recommend()` |
| Private helpers | `_snake_case` | `_step_5w1h()` |
| Constants | `UPPER_CASE` | `DEFAULT_TOP_K` |

### File Structure

```
src/loom/
├── __init__.py          # Public API exports + version
├── __main__.py          # `python -m loom` entry
├── config.py            # Configuration management (env vars > yaml > defaults)
├── recommend.py         # Four mandatory steps: 5W1H → Hexagram → Recall → EVAL
├── eval.py              # Multi-dimension EVAL scoring
├── hexagram.py          # 64 hexagram Unicode mapping + chain logic
├── analyzer/
│   ├── solidifier.py    # Knowledge persistence
│   ├── audit.py         # Quality audit
│   └── maintenance.py   # Periodic maintenance tasks
├── finder/
│   ├── router.py        # Model matching (task ⊗ model ⊗ status)
│   ├── registry.py      # Model registry
│   ├── matcher.py       # Embedding-based matching
│   ├── heartbeat.py     # Availability probes
│   ├── explorer.py      # Model discovery
│   ├── context_space.py # Dynamic embedding buffer
│   └── status_cache.py  # Freshness tracking
├── knowledge/
│   ├── ingest.py        # Document ingestion pipeline
│   ├── flywheel_events.py # E1-E5 lifecycle events
│   ├── classify/        # Hierarchical domain/level/type classification
│   ├── rag/             # Retrieval engine + chunker + vector store
│   ├── quality/         # Noise filtering
│   └── context/         # Budget-aware context assembly
├── manager/
│   ├── shuttle.py       # Flow visualization (Step dataclass, @step decorator)
│   ├── client.py        # Conversation manager singleton
│   ├── factory.py       # Turn/Session/Conversation factory methods
│   └── models.py        # Three-tier data models
├── scheduler/           # Task scheduling + WSL compensation
├── kpak/                # Knowledge package export/import
└── tools/
    └── hermes_tools.py  # Hermes Agent bridge functions
```

### What Not to Do

- **No hardcoded paths or model names** — use `config.py` or environment variables.
- **No embedding model coupling** — the codebase references `config.embedding_model` generically, never by name.
- **No credentials in code** — API keys live in `.env`, loaded by `LoomSecrets`.
- **No overly complex abstractions** — avoid ActionRegistry-style over-engineering. If a pattern isn't actively used by runtime code, it doesn't belong.

---

## Testing

### Running Tests

```bash
# Full suite
python3 -m pytest tests/ -v

# Specific test file
python3 -m pytest tests/test_loom.py -v

# With coverage
python3 -m pytest tests/ --cov=src/loom/
```

### Test Requirements

- **All code must pass** `pytest tests/` before merging.
- **New features require new tests** — at minimum, a test for the public API surface.
- **No PR is accepted with failing tests.** Period.
- **Test files mirror the source structure:** `tests/test_{module}.py`.

### What to Test

| Component | Test Priority | Example |
|-----------|--------------|---------|
| `recommend()` | High | Four steps produce correct output |
| `solidify()` | High | Insight is persisted and retrievable |
| `find_partners()` | Medium | Candidates are ranked by score |
| `Shuttle` | Medium | Step lifecycle, flow_chain formatting |
| `VectorStore` | High | CRUD operations, metadata preservation |
| `Hexagram` | Low | off-by-one regression (was broken in v4.0.2) |

---

## Pull Request Workflow

### Branch Strategy

```
master (stable release)
  └── feat/short-description  (feature branches)
  └── fix/short-description   (bug fixes)
  └── docs/short-description  (documentation only)
```

### PR Lifecycle

1. **Create a feature branch** from `master`:
   ```bash
   git checkout master
   git pull origin master
   git checkout -b feat/my-feature
   ```

2. **Make your changes** — one logical change per commit (see [Commit Guidelines](#commit-guidelines)).

3. **Run tests locally**:
   ```bash
   python3 -m pytest tests/ -v
   ```

4. **Push and open a PR** against `master` with a clear description:
   - What problem does this solve?
   - What changed? (architecture, API, performance)
   - How was it tested?

5. **Address review feedback** — expect at least one round of review.

6. **Squash-merge** into `master` when approved. Keep the squashed commit message descriptive.

---

## Commit Guidelines

### Format

```
<type>: <short description>

<optional body — one or more paragraphs>
```

Types:
- `feat` — new feature
- `fix` — bug fix
- `docs` — documentation only
- `refactor` — code restructuring with no behavior change
- `test` — adding or updating tests
- `chore` — build, dependencies, tooling
- `perf` — performance improvement

### Examples

```
feat: hexagram_judgment — 64 classical Zhouyi judgments

Adds hexagram_judgment() that returns the classical judgment text
for each of the 64 hexagrams. Integrated into inject() and
hexagram_pulse() for richer decision context.

Test: 43/43 passed
```

```
fix: off-by-one in hexagram_lookup

hexagram_display() was using 'hid' directly as a list index, causing
hexagram #1 to return the second entry instead of the first. Fixed by
using 'hid - 1' for array access.

Closes #12
```

```
chore: clean up checkpoints directory

Remove old flywheel artifacts (v14, v16-v18, rl_best) that were
specific to the development environment. Keep only minimal.pt as the
canonical seed checkpoint.
```

### Rules

- One logical change per commit. If your PR has two unrelated features, split them.
- Use `git rebase -i` to clean up commit history before pushing.
- Do not commit generated files (checkpoints, __pycache__, .kpak, data/).
- Do not commit credentials, tokens, or local paths.

---

## Documentation

- **Every public function** must have a docstring (Google-style).
- **New features** should update:
  - `CHANGELOG.md` (user-facing changes)
  - Relevant docstrings
  - If applicable: `README.md`, `ARCHITECTURE.md`, or `docs/`
- **Inline comments** explain *why*, not *what*. Code should be self-documenting for *what*.
- **Design decisions** go in docstrings or `ARCHITECTURE.md`, not as inline comments.
- **Non-obvious pitfalls** should be documented near the code that the pitfall applies to.

---

## Feature Requests & Bug Reports

### Filing an Issue

Use GitHub Issues with one of these labels:

| Label | When to Use |
|-------|------------|
| `bug` | Something doesn't work as documented |
| `enhancement` | New feature or improvement |
| `documentation` | Missing or unclear docs |
| `question` | You're not sure how something works |

### Good Bug Report

```
**Describe the bug**
recommend() crashes when user input is empty.

**To reproduce**
1. Call recommend("")
2. See error: AttributeError ...

**Expected behavior**
Should return a Recommendation with empty fields or raise a clear ValueError.

**Environment**
- LOOM version: 4.0.3
- Python: 3.11
- OS: Ubuntu 24.04 WSL
```

---

## Advanced: Knowledge Ingestion Contributions

If you're contributing new knowledge sources (SAP documentation, training materials, etc.):

1. Place source files in a known directory (e.g., `data/sources/`).
2. Run the ingestion pipeline manually:
   ```bash
   python3 -c "from loom import recommend; from loom.knowledge.ingest import ingest; print(ingest('path/to/file'))"
   ```
3. Verify the chunks are retrievable:
   ```bash
   python3 -c "from loom import recommend; r = recommend('your test query'); print(len(r.knowledge_items))"
   ```
4. Document the source in `CHANGELOG.md` under a new section: `### Knowledge Ingestion`.
5. Do not commit the source files themselves — only the resulting ChromaDB data.

---

## Final Note

> LOOM is a framework that learns. Your contributions help it learn better.
>
> The best PR is not the one with the most lines — it's the one that makes the next contributor's job easier.
>
> **知之为知之，不知为不知，是智也。**
> *To know what you know, and know what you don't — that is wisdom.*

---

[MIT](LICENSE) © ahillzhao-msn
