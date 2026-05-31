# KAFED Changelog

## v4.0.3 (2026-05-30) — Fix: ChromaDB Singleton Conflict

### Fixes

- **VectorStore ChromaDB singleton** — Added `_shared_clients` class-level cache to prevent `ValueError: An instance of Chroma already exists` when multiple `VectorStore`/`ContextProvider` instances are created in the same process. ChromaDB's internal singleton rejects a second `PersistentClient` if settings differ even slightly. Fix: first init creates the client; reuses cached client on subsequent inits.

### Tools

- **`~/.hermes/scripts/loom-ingest.py`** — Hybrid three-tier PDF ingestion tool (markitdown → docling → pymupdf). Supports single file and batch directory mode. Installed as part of the SOC ingestion campaign.

### SOC Ingestion Campaign

| Course | Textbooks | PPTs | Quizzes | Total Chunks |
|--------|-----------|------|---------|-------------|
| SOC101 Intro to Sociology | 21 chapters (markitdown) | 9 lecture sets | 16 chapters (247 qs) | ~4,500 |
| SOC102 Social Problems | 15 chapters + textbook | 5 lecture sets | — | ~2,000 |
| SOC206 Social Psychology | — | 15 chapter slides | 15 chapters (220 qs) | ~1,600 |
| SOC110 Marriage & Family | — | 3 lecture sets | — | ~600 |
| Other courses | Partial | Partial | — | ~1,700 |
| **Total** | | | | **10,626 chunks** (10,407 sociology) |

### Notes

## v4.0.2 (2026-05-30) — Fix: Hexagram Off-by-One & Output Formatting

### Fixes

- **Off-by-one in hexagram lookup** — `hexagram_display()`, `hexagram_symbol()`, `hexagram_judgment()`, `hexagram_chain()`, `hexagram_chain_compact()` all now use `hid+1` to correctly index into the 64-hexagram list. Previously, hexagram ID `1` would look up index `1` (the second hexagram) instead of index `0` (the first, ䷀ 乾). Hydrological hexagrams (水, 坎, etc.) were unaffected because their `hid` happened to match; the bug caused wrong symbols/names for all others.
- **Missing space in `inject()`** — Line 143 now adds a space between hexagram symbol and name (e.g. `䷀ 乾` instead of `䷀乾`).
- **Missing space in `hexagram_pulse()`** — Same fix: space between hexagram symbol and Chinese name in pulse output.

### Tests

- **43/43 passed** — All existing tests continue to pass with no regressions.

## v4.0.1 (2026-05-30) — Refactor: Clean Structure, Step Abstraction, Shuttle Takes Over

### Breaking Changes

- **`flow.py` deleted** — Fully replaced by Shuttle. `flow_enabled()` now respects the same `LOOM_SHUTTLE` default as `shuttle_enabled()` (default: ON). `[LOOM Pipeline]` no longer appears.
- **`director/` flattened** — `recommend.py`, `eval.py`, `hexagram.py` promoted to `src/loom/`. All import paths updated.
- **`loom/loom/` → `manager/`** — Nested directory flattened: `manager.py` → `client.py`, `shuttle.py`, `models.py`, `factory.py` moved to `manager/`.
- **`finder/` output migrated** — `flow.chain/hop/stop` replaced with `Shuttle.display()`.

### New Features

- **`Step` dataclass** (`manager/shuttle.py`) — Universal event record with `CxSyTz-N` ID, module, action, detail, status, duration.
- **`@step()` decorator** — Wraps any function, auto-generates ID, measures duration, registers to `Shuttle._steps`. try/except handled transparently.
- **Lifecycle events as Steps** — Session open/close (`S/session_open`/`session_close`), Conversation open/close (`C/conversation_open`/`conversation_close`) registered in `Shuttle._steps`.
- **`Shuttle.register_step()`** — Auto-generates `CxSyTz-N` ID from manager context when called without explicit ID.
- **`recommend()`** now calls `Shuttle.reset_steps()` at entry and `Shuttle.emit_flow()` at exit. Four step functions decorated with `@step()`.
- **Solidify emits via Shuttle** — `solidifier.py` removed `flow_step()` dependency; outputs `[ LOOM ]  D固(...)`.
- **`Shuttle.steps_snapshot()`** — Read-only access to the unified step log. Filter by `id.startswith("C1S2T3")` for per-layer or per-turn queries.

### Fixes

- **ID collision fix** — `ingest.py`: UUID suffix appended on MD5 collision.
- **flow_enabled() default** — Changed from `""` (fallthrough to `isatty()`) to `"1"` (consistent with shuttle).
- **`TurnFactory.from_recommend()`** — Accepts `str`, `tuple`, `Step`, or legacy `FlowEntry` objects.

### Documentation

- **SOUL-template.md** — Cleaned up, simplified Chinese, removed over-specific technical content.
- **README.md** — Advanced Hermes Plugin Integration section for `loom-hooks` and `yicenet-hooks`.
- **ARCHITECTURE.md** — Updated import path in code example.
- **CHANGELOG.md** — This entry.
- **Tests** — 43/43 passed (`test_loom.py`). Test suite path imports updated for new directory structure.

## v4.0.0 (2026-05-28) — Conversation Context (Loom)

### Architecture

- **New: Conversation Context (Loom)** — Cross-cutting conversation management layer wrapping the recommend → solidify cycle. Weaves individual turns into coherent conversations (Conversation → Session → Turn hierarchy).
- **New: ARCHITECTURE.md Section 3** — Full documentation of the Loom architecture, three-tier model, auto-integration, and Producer/Consumer flywheel interface.

### New Modules

- **`loom/manager.py`** — `_ConversationManager` singleton. `start_turn()`, `end_turn()`, `get_or_create_conversation()`, `close_conversation()`, `record_solidify()`, `reward_for_flywheel()`.
- **`loom/models.py`** — Three-tier data models: `TurnRecord`, `SessionRecord`, `ConversationRecord` with reward signals, hexagram pattern detection, key turn scoring, and session summarization.
- **`loom/factory.py`** — `TurnFactory`, `SessionFactory`, `ConversationFactory` with create/from_recommend/from_dict/is_expired/should_close methods.
- **`loom/shuttle.py`** — Shuttle (梭子) visualization: `flow_chain()`, `hexagram_trail()`, `session_tapestry()`, `conversation_tapestry()`. Optional YiCeNet dependency with graceful fallback.

### Integration

- **`solidify()` auto-records to active Loom conversation** — `analyzer/solidifier.py` now calls `loom.record_solidify()` automatically when a conversation is active. Zero Agent code change.
- **`close_conversation()` submits to YiCeNet flywheel** — Calls `submit_trajectory()` with complete reward signal. Non-fatal (silent no-op when YiCeNet not installed).
- **External Producer API** — `submit_trajectory()` standard interface for any module to feed training data to YiCeNet's flywheel buffer.

### Documentation

- **ARCHITECTURE.md** — New Section 3 (Conversation Context / Loom) with architecture diagram, three-tier table, auto-integration examples, Shuttle modes, Producer/Consumer diagram, design decisions.
- **docs/loom-architecture.md** — Full technical reference: data model, lifecycle, reward signal table, Shuttle API, Factory API.
- **README.md** — Added Loom section (concept-level).

### Fixes

- **`loom/factory.py`** — `from_recommend()` now accepts both FlowEntry objects and simple tuples (tuple compatibility for Agent code and tests).
- **`loom/shuttle.py`** — `hexagram_trail()` graceful fallback when YiCeNet not installed (uses `#N` instead of Unicode hexagram symbols).

### Tests

- **`tests/test_loom.py`** — 34 new tests: Conversation lifecycle (5), Turn lifecycle (5), Solidify integration (3), Reward/flywheel (3), Shuttle (7), Model properties (8), Solidifier API (2).

---

### Architecture Redesign

- **Single entry point**: `director.recommend()` replaces multi-variant Pipeline (soul_core/quick/deep). Four mandatory steps per turn: 5W1H → Hexagram → Knowledge Recall → EVAL. No step can be skipped.
- **Agent owns decisions, KAFED provides context**: KAFED no longer attempts to split tasks, select models, or orchestrate execution. The Agent receives enriched context and acts freely.
- **Frontend/Backend separation**: Director + Finder are the decision-support frontend (per-turn). Analyzer + Scheduler are the learning backend (async).
- **Removed Executor layer**: DAG scheduling, dispatcher, and feedback loop removed. Hermes `delegate_task` handles parallel subtask execution natively.
- **Removed Backlog layer**: KAFED's custom backlog replaced by Hermes native backlog.
- **Removed ActionRegistry**: Over-engineered Command pattern that was registered but never driven by PipelineRunner.

### New Modules

- **`director/hexagram.py`**: Full 64-hexagram Unicode mapping (U+4DC0–U+4DFF) with Chinese/English names, six-line monograms (⚊⚋), hexagram chain tracking, and compact display (`䷀→䷫→䷠→䷋`).
- **`director/recommend.py`**: Single entry point. Full 5W1H decomposition (heuristic, domain-aware), YiCeNet integration with chain history, ContextProvider recall, EVAL with hexagram modulation.
- **`analyzer/solidifier.py`**: Extracted solidify + session_end_audit from deleted entry.py. Clean API: `solidify(insight, domain, source)`.
- **`scheduler/`**: Task scheduling with WSL compensation. `TaskRegistry` + `TaskRunner` + 5 built-in tasks (heartbeat, centroid_flywheel, explorer_scan, knowledge_audit, flywheel_daily).
- **`tools/hermes_tools.py`**: New canonical location for Hermes tool functions: `kafed_recommend`, `kafed_find_partners`, `kafed_solidify`, `kafed_query`, `kafed_ingest`, `kafed_status`, `kafed_classify`, `kafed_flow`.
- **`knowledge/ingest.py`**: Rewritten. Added `batch_ingest()` and `batch_ingest_files()` for offline scheduled ingestion. Fixed metadata preservation: `chunk_document()` heading chain, quality score, character count, and chunk index now stored in ChromaDB metadata (was lost in v2).
- **5W1H Decomposition**: Heuristic extraction of What/Why/Who/Where/When/How from user input, used as enriched input signal for YiCeNet hexagram prediction.

### Module Renames

| Old | New | Reason |
|-----|-----|--------|
| `analyzer/pulse.py` | `analyzer/maintenance.py` | "Pulse" was vague |
| `analyzer/kb_audit.py` | `analyzer/knowledge_audit.py` | No abbreviations |
| `knowledge/flywheel/event_checker.py` | `knowledge/flywheel_events.py` | Flatter, clearer |
| `client/flow.py` | `flow.py` | Not a "client" — it's a visualizer |
| `client/kafed_tool.py` | `tools/hermes_tools.py` | Hermes integration, not a client |

### Removed

| Module | Reason |
|--------|--------|
| `executor/` (5 files) | DAG/dispatch/engine — Hermes `delegate_task` handles this |
| `entry.py` | Replaced by `director/recommend.py` |
| `backlog.py` | Hermes native backlog |
| `director/planner.py` | Task planning is Agent's responsibility |
| `director/decision.py` | Decision tree is Agent's judgment |
| `action_registry.py` | Registered but never driven by PipelineRunner |
| `*/actions.py` (5 files) | All action registrations |
| `scripts/` (12 one-off scripts) | Admin tools cleaned: recluster, sub_cluster, name_subclusters, validate_hierarchy, update_cluster_metadata, knowledge_scanner, convert_blog_inline, batch_ingest, batch_ingest_to_kafed, download_models, ingest_new_formats, scan_and_ingest |

### Renamed Scripts

| Old | New |
|-----|-----|
| `scripts/backlog.py` | Removed (Hermes native) |
| `scripts/centroid_flywheel.py` | `scripts/cron/centroid_flywheel.py` |
| `scripts/kafed-bootstrap.sh` | `scripts/install/kafed-bootstrap.sh` |
| — | `scripts/install/symlink-tools.sh` (new) |

### Hexagram Display

- Hexagram output now shows Unicode symbol + name + six-line monograms: `䷀ 乾 ⚊⚊⚊⚊⚊⚊`
- Hexagram chain display: `䷀→䷫→䷠→䷋`
- Candidate hexagrams shown as symbol row
- English environment: `䷀ Qian / The Creative`
- All 64 hexagrams mapped in `director/hexagram.py` with King Wen sequence

### Metadata Preservation Fix

`_ingest_to_kafed()` now stores `chunk_document()` output completely:
- `heading` — section title
- `heading_chain` — full breadcrumb path (comma-joined)
- `quality_score` — 0.0–1.0 quality rating
- `chars` — character count
- `chunk_index` — position in document

Previously only `domain` and `source` were stored — all structural metadata was discarded.

### Tests

- `tests/flow_demo.py`: Two-scenario demo (simple SAP task + complex KAFED refactoring with find_partners). Shows compact (arrow chain) and detailed (bus-stop) FlowVisualizer modes with hexagram symbols.
- `tests/km_ingest_demo.py`: Two-scenario KM ingestion test (online solidify + offline batch_ingest_files). Validates RAG recall, metadata preservation, and flywheel event triggering.
- `tests/test_pipeline.py`: Updated for v3 API (recommend, solidify, find_partners, scheduler).

### Documentation

- **README.md**: Rewritten — community-facing with Before/After metrics, quick start, Personal AI Manifesto.
- **ARCHITECTURE.md**: Rewritten — complete technical design of v3.0, no legacy references.
- **SOUL.md**: Updated — new turn flow: `kafed_recommend → Agent acts → kafed_solidify`.

---

## v2.2.2 (2026-05-26)

### Fixes
- `kafed.entry.plan()` deleted — Director now calls `finder.router.find_partners()` directly
- README API examples updated to reflect deleted `plan()` function
- `kpak` module activated with CLI entry point and exports
- `backlog_data` default path fixed (was `~/.kafed/`, now `~/.hermes/data/`)

### Architecture
- Finder 3-vector aggregation finalized (task ⊗ model ⊗ status)
- Explorer single-source discovery from Hermes config.yaml
- Heartbeat exponential freshness decay with backoff scheduling
- Dynamic PricingTable with cache file

---

## v2.2.0 (2026-05-25)

- Bootstrap installation system (7-phase auto-init)
- Finder v2 dual-mode routing (fast_route + full_route)
- ContextProvider budget-aware recall with soft classification
- Explorer full Hermes model discovery with role detection
- Heartbeat v2: async exponential decay
- YiCeNet soft dependency integration

---

## v2.1.0 (2026-05-23)

- Six-phase hierarchical clustering (Entity + Registry)
- soft_classify module with boundary expansion
- Level 33 + Type 98 domain naming
- Centroid flywheel cron (weekly)
- ContextProvider multi-source embedding recall

---

## v2.0.0 (2026-05-22)

- Five-layer architecture: Director/Finder/Executor/Analyzer/Knowledge
- Global config system: KafedConfig + KafedSecrets
- Executor supervised feedback loop
- FlowVisualizer (bus-stop style)
- Pipeline commitment chain (soul_core/quick/deep)

---

## v1.0.0 (2026-05-20)

- Initial release
- ChromaDB vector store + bge-small RAG engine
- Core flywheel framework
- MIT License
