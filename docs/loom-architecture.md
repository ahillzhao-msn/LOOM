# Loom (织机) — Conversation-level Session Management

## 概述

Loom 是 KAFED v4 的交談級會話管理系統。將分散的對話輪次編織成連貫的知識結構，為飛輪提供完整的決策軌跡。

```
三層資料結構：
  Conversation (邏輯主體) → 1:n → Session (技術切片) → 1:n → Turn (原子輪次)
```

## 為什麼需要 Loom

| 問題 | Loom 的方案 |
|------|-------------|
| Hermes session 由技術事件（重啟、idle）決定邊界 | Loom Conversation 純邏輯邊界，跨技術 session |
| KAFED 無法感知 Agent 每輪的完整決策上下文 | Loom Turn 記錄 卦/召/評/固 全軌跡 |
| YiCeNet 飛輪只能從 session DB 碎片化學習 | Loom 聚合完整 Conversation 獎勵信號 |
| FlowVisualizer 只能展示當輪流程 | Shuttle 提供跨層級多視角織錦 |

## 三層資料結構

### Conversation（邏輯主體）

- `conversation_id` — 12 位 hex UUID
- 跨技術邊界：不因 idle、重啟、系統輪而中斷
- 空閒超過 24h 自動閉合
- 閉合時聚合獎勵信號 → 提交到 YiCeNet 飛輪

### Session（技術切片）

- `session_id` — 12 位 hex UUID
- 因 idle（30 分鐘）或顯式中斷而自然閉合
- 不切斷 Conversation 的邏輯連續性
- 聚合每輪的 solidify 日誌、卦演化模式、關鍵轉折點

### Turn（原子輪次）

- 對應 Agent 的「recommend → 行動 → solidify」循環
- 記錄：query、卦象、知識召回分佈、EVAL 評分、步驟鏈、token 用量
- 用戶回饋：`affirmation` / `correction` / None
- 固化結果

## 生命週期

```
Agent 啟動
  │
  ├─ loom.start_turn(query, hexagram, knowledge, eval_score, steps)
  │    └─ 自動 create/get Conversation
  │         └─ 自動 create/get Session（過期閉合）
  │              └─ 創建 TurnRecord
  │
  ├─ Agent 工作（recommend → 行動）
  │
  ├─ solidify() 自動 record_solidify(result) 到活躍 Session
  │
  ├─ loom.end_turn(user_feedback="affirmation"|"correction")
  │
  └─ Conversation 閉合（idle/explicit）
       └─ reward_for_flywheel() → submit_trajectory() → YiCeNet 飛輪
```

## 獎勵信號（飛輪輸入）

`ConversationRecord.reward_for_flywheel()` 生成的獎勵包包含：

| 信號 | 意義 |
|------|------|
| n_turns | 對話深度 |
| total_tokens | 成本 |
| token_efficiency | token/輪 效率 |
| hexagram_evolution | 卦演化序列 |
| hexagram_q_avg | 平均信心度 |
| session_patterns | 各 session 穩定/漂移/跳躍 |
| correction_rate | 用戶修正率（越低越好） |
| knowledge_reuse_rate | 知識重複利用率 |
| total_solidifies | 固化次數 |
| duration | 對話時長 |

## YiCeNet 飛輪 Producer/Consumer

### 外部 Producer 介面

任何模組都可通過 `submit_trajectory()` 標準 API 向 YiCeNet 提供訓練資料：

```python
from yicenet.flywheel import submit_trajectory

submit_trajectory({
    "producer": "loom",          # 來源標識
    "version": 1,                # schema 版本
    "conversation_id": "...",
    "trajectory": {...},         # reward_for_flywheel() 輸出
    "embedding": [...],          # topic centroid
})
```

### 兩路合流

```
                    submit_trajectory(data)
                    ┌──────────┐
Loom ──────────────►│          │
                    │  YiCeNet  │
Hermes Agent ──────►│  FLYWHEEL├──→ flywheel_buffer.jsonl ──→ RL train
                    │  _BUFFER │
Future Producer ───►│          │
                    └──────────┘
                    (記憶體緩衝，cron 消費)
```

- **內部 Producer**（session DB 掃描）→ 保留，向後相容
- **外部 Producer**（Loom，其他）→ `submit_trajectory()` 標準介面
- 兩路徑在 flywheel_buffer.jsonl 合流，訓練管道不關心來源
- Loom 調用是 try/except 包裝的——YiCeNet 未安裝時優雅降級

## Shuttle (梭子)

Shuttle 是 Loom 的資訊探針，提供四種織法展示：

1. **flow_chain(steps, end)** — 當輪流程鏈。取代舊 compact 模式
2. **hexagram_trail(ids)** — 卦象演化足跡（跨輪次）。需 YiCeNet 安裝時顯示 Unicode 卦符，否則顯示 `#N`
3. **session_tapestry(session)** — 單一 session 的完整面貌。含卦鏈、關鍵輪次標記
4. **conversation_tapestry(conv)** — 整場對話的織錦。跨 session 卦演化、效率/修正率統計

### 使用方式

```python
from kafed.loom.shuttle import Shuttle

# 流程鏈
print(Shuttle.flow_chain(["D問", "D卦(困)", "D召(K[3])", "D評(T2)"], end="D固"))
# D問 -> D卦(困) -> D召(K[3]) -> D評(T2) -> D固

# Session 全貌
tapestry = Shuttle.session_tapestry(session)
Shuttle.display(tapestry)  # 輸出到 stderr
```

### 全局開關

環境變量 `LOOM_SHUTTLE` 控制輸出：
- `1` / `true` / `yes` / `on` — 啟用
- 其他值或未設定 — 禁用

## API 速查

### Manager

| 方法 | 說明 |
|------|------|
| `get_or_create_conversation()` | 獲取/創建 Conversation |
| `close_conversation(reason)` | 閉合並提交飛輪獎勵 |
| `start_turn(query, ...)` | 開始新輪（auto session） |
| `start_turn_from_recommend(query, hexagram, ...)` | 從 recommend 結果開始 |
| `end_turn(user_feedback)` | 結束輪次 |
| `record_solidify(result)` | 記錄固化結果 |
| `reward_for_flywheel()` | 獲取當前獎勵信號包 |
| `status()` | 快照 |

### Factory

| 方法 | 說明 |
|------|------|
| `TurnFactory.create(...)` | 從零建立 Turn |
| `TurnFactory.from_recommend(...)` | 從 recommend 結果建立（tuple/物件兼容） |
| `SessionFactory.create(conversation_id)` | 建立 Session |
| `SessionFactory.is_expired(session)` | 30min idle 檢測 |
| `ConversationFactory.create(topic_centroid)` | 建立 Conversation |
| `ConversationFactory.should_close(conv)` | 24h idle 自動關 |

### Model

| 屬性 | 所在類 | 說明 |
|------|--------|------|
| `is_efficient` | TurnRecord | 步數 ≤ 6 |
| `had_correction` | TurnRecord | 被糾正 |
| `had_affirmation` | TurnRecord | 被肯定 |
| `turn_count` | SessionRecord | 輪數 |
| `hexagram_pattern()` | SessionRecord | 穩定/漂移/跳躍 |
| `key_turns(n)` | SessionRecord | 最關鍵 n 輪 |
| `summarize()` | SessionRecord | 摘要 dict |
| `knowledge_reuse_rate` | ConversationRecord | 知識重複率 |
| `reward_for_flywheel()` | ConversationRecord | 飛輪獎勵包 |
