# Hermes Plugin Hooks: Four-Hook Architecture Evolution

> Hermes Agent 的四鉤子架構設計——YiCeNet 與 LOOM 如何透過 plugin hooks
> 將每次 LLM 調用、每次工具調用，變為持續學習的信號。
>
> 謹慎而大膽。武器級更新，初期只觀察不阻斷。

## 背景：從工具到鉤子

在引入 plugin hooks 之前，YiCeNet 和 LOOM 都是**被動工具**——Agent（LLM）在 SOUL.md 指令下主動調用：

```
舊模式：
  SOUL.md → "調用 loom_recommend()" → LLM 調用工具 → 返回結果
  SOUL.md → "調用 yicenet_predict()" → LLM 調用工具 → 返回結果
  SOUL.md → "調用 loom_solidify()" → LLM 調用工具 → 返回結果
```

**問題**：LLM 可能忘記調用、調用時機不精確、無法攔截工具執行層面的事件。

新模式：**Hermes Plugin Hooks**——在系統層自動觸發的 lifecycle callbacks：

```
新模式：
  Hermes Agent Loop → fire pre_llm_call → 鉤子自動執行 → 返回 context
                    → fire pre_tool_call → 鉤子自動檢查
                    → fire post_tool_call → 鉤子自動學習
                    → fire post_llm_call → 鉤子自動閉環
```

## 四鉤子架構

### 鉤子位置

```
               User Input
                   │
         ┌── Hook 1: pre_llm_call ──┐
         │  YiCeNet: 卦象注入(僅當   │
         │    LOOM 不活躍時)         │
         │  LOOM:    5W1H+知識+EVAL │
         └───────────┬──────────────┘
                     ↓
                 LLM 生成
                     ↓
         ┌── Hook 3: pre_tool_call ──┐
         │  YiCeNet: 工具卦象校準     │
         │  LOOM:    工具查重/路由    │
         └───────────┬──────────────┘
                     ↓ (every tool call)
         ┌── Hook 4: post_tool_call ─┐
         │  YiCeNet: tool-level reward│
         │  LOOM:    選擇性 solidify  │
         └───────────┬──────────────┘
                     ↓ (back to LLM or exit)
         ┌── Hook 2: post_llm_call ──┐
         │  YiCeNet: flywheel 反饋    │
         │  LOOM:    輕量會話記錄     │
         └───────────┬──────────────┘
                     ↓
               回應給用戶
```

### 可用鉤子列表（來自 Hermes VALID_HOOKS）

| 鉤子 | 觸發點 | YiCeNet | LOOM |
|------|--------|---------|------|
| `on_session_start` | session 創建 | baseline 卦象 | — |
| `pre_llm_call` | LLM 調用前，可返回 context 注入 | 卦象 context（僅無LOOM時） | recommend context |
| `post_api_request` | API 返回後 | token 累積 | token 累積 |
| `pre_tool_call` | 工具調用前，可返回 block message | 卦象校準（僅觀察） | 工具查重（僅觀察） |
| `post_tool_call` | 工具返回後 | reward 信號 | 新工具 solidify |
| `post_llm_call` | LLM 回應完成後 | flywheel 反饋 | 輕量記錄 |
| `on_session_end` | session 結束 | 日誌清理 | 日誌清理 |

## 每個鉤子的設計

### Hook 1: pre_llm_call

**LOOM 活躍時**：

LOOM plugin 觸發 `loom_recommend()` → 內部含 5W1H 分解、YiCeNet 卦象（已吸收）、RAG 知識召回、EVAL 評分 → 返回完整 context。

YiCeNet plugin 檢測 `_loom_hooks_active()` → **跳過**，不重複。

**LOOM 不活躍時（YiCeNet standalone）**：

YiCeNet plugin 跑 `yicenet_predict(user_message)` → 卦象預判 → 注入簡短 context。

### Hook 2: post_llm_call

**設計約定：Option B（輕量優先）**

Plugin 層在 post_llm_call **不做 heavy solidify**。只做：
- YiCeNet：寫 reward signal 到 flywheel buffer（token cost + 效率估算）
- LOOM：寫 session 概要到 flywheel buffer（不寫入 KAFED）

Heavy solidify 仍保留在 SOUL.md，由 Agent 手動調用 `loom_solidify()`。

**理由**：每輪都會觸發 post_llm_call。如果每輪都 solidify，KAFED 會淹沒在「普通對話」的噪聲中。只有 Agent 認為**有意義的 insights** 才應該寫入知識庫。

### Hook 3: pre_tool_call

**核心紀律：初期只觀察，不阻斷。**

pre_tool_call 可以返回 block message 阻止工具執行，但初期階段**兩個 plugin 都只返回 None**。block 權限在行為穩定後逐步開放。

**LOOM plugin**：
- 過濾條件：僅對 `write_file`、`patch`、`terminal`（command 含關鍵字）觸發
- 行為：用 KAFED 語義搜索查詢是否有已有工具匹配當前操作
- 如果匹配到已有工具：僅 log，不干預
- 不匹配：正常執行

**YiCeNet plugin**：
- 過濾條件：同上（僅對代碼生成類工具）
- 行為：跑一次 `yicenet_predict` 做卦象校準——檢查「這個工具的執行方向是否與當前輪的卦象一致」
- 僅 log 不一致情況，不阻斷

### Hook 4: post_tool_call

**核心設計：僅在新工具創建時 solidify，最嚴格抑噪。**

「新工具」的判定條件（**全部**滿足才算）：

```
① 工具名是 write_file / patch / terminal
② write_file/patch 的目標路徑在 ~/.hermes/hermes-agent/tools/ 下
   或 terminal command 含 > 或 >> 且目標在 tools/ 下
③ 文件內容包含 "registry.register("（確認是 Hermes 工具非臨時腳本）
④ 該文件之前不存在（非覆蓋已有文件）
⑤ 工具執行成功（exit code = 0）
⑥ 內容不含 "Draft" / "WIP" / "TODO" 等草稿標記
```

**不滿足任一條件 → 跳過，0ms 開銷。**

**LOOM plugin**（滿足條件時）：
- 調用 `loom_solidify()` 將新工具註冊到 KAFED
- domain 標記為 `toolkit`

**YiCeNet plugin**（每次都執行，不區分）：
- 成功 → 正向 reward 寫入 flywheel buffer
- 失敗 → 負向 reward
- 不寫入 KAFED（reward signal 專用）

## 時間動態：工具包生長曲線

```
Day 1:   工具包空。pre_tool_call 查重 → 0 匹配
         每個代碼生成請求都創建新文件
         post_tool_call 逐個註冊 → 工具包從 0 開始增長

Week 1:  工具包 ~20 工具。偶爾查重命中 → LLM 復用
         新工具創建速度放緩

Month 1: 工具包 ~50+ 工具。常見模式全覆蓋
         新工具創建趨零，復用成為默認行為

Month 3: 工具包成熟。pre_tool_call 查重 >80% 匹配率
         系統層面的「工具記憶」形成
```

## 安全與風險

### 風險矩陣

| 風險 | 嚴重度 | 緩解 |
|------|--------|------|
| pre_tool_call 對 read-only 工具也做 check | 低 | 按 tool_name 過濾 |
| LOOM 的 RAG 查重導致代碼生成變慢 | 低 | 啟發式過濾 terminal command |
| post_tool_call 過度固化噪聲 | **高** | 六條件嚴格判斷，任何不滿足即跳過 |
| pre_tool_call 誤阻斷正常操作 | **高** | 初期 block 禁用，只觀察 |
| LOOM + YiCeNet plugin 衝突 | 低 | `_loom_hooks_active()` 統一跳過邏輯 |
| post_llm_call 與 SOUL.md solidify 重複 | 中 | Option B：plugin 輕量，Agent 手動 |
| 兩 plugin context 疊加膨脹 | 低 | 有 LOOM 時 Y 跳過，無疊加 |

### 安全邊界

1. **pre_tool_call 的 block 權限在初期關閉**
2. **post_tool_call 的 solidify 僅在六條件全滿足時觸發**
3. **LOOM 與 YiCeNet 互斥存在**：LOOM 活躍時 YiCeNet 自動跳過
4. **每個鉤子內部 try/except**：異常不傳播，不中斷 Hermes agent loop

## 實現方案

### YiCeNet plugin 修改

`~/YiCeNet/scripts/install/__init__.py`：

| 改動 | 說明 |
|------|------|
| 新增 `pre_tool_call` handler | 卦象校準，僅過濾工具，不阻斷 |
| 新增 `post_tool_call` handler | tool-level reward 到 flywheel |
| 更新 `register()` | 註冊新鉤子 |
| 更新 `plugin.yaml` | hooks 列表加 pre/post_tool_call |

### LOOM plugin 修改

`~/LOOM/scripts/install/__init__.py`：

| 改動 | 說明 |
|------|------|
| `post_llm_call` 改為輕量 | 移除 heavy solidify，僅寫 flywheel |
| `pre_llm_call` 移除冗餘 YiCeNet | LOOM 的 recommend 已內部調用 |
| 新增 `pre_tool_call` handler | KAFED 查重，僅觀察不阻斷 |
| 新增 `post_tool_call` handler | 六條件判新工具，僅新工具時 solidify |
| 更新 `register()` | 註冊新鉤子 |
| 更新 `plugin.yaml` | hooks 列表加 pre/post_tool_call |

### SOUL.md 修改

| 改動 | 說明 |
|------|------|
| 移除 `loom_recommend()` 強制調用 | Plugin 自動處理 |
| 保留 `loom_solidify()` 手動回退 | Option B：Agent 控制 heavy solidify |
| 保留基石/道法術哲學/四省/卦鏈 | 不變 |
| 新增「若 plugin 故障」手動回退指令 | 安全網 |

## 驗證清單

### 安裝驗證

```bash
# YiCeNet plugin
ls ~/.hermes/plugins/yicenet-hooks/
cat ~/.hermes/plugins/yicenet-hooks/plugin.yaml
hermes plugins list | grep yicenet

# LOOM plugin
ls ~/.hermes/plugins/loom-hooks/
cat ~/.hermes/plugins/loom-hooks/plugin.yaml
hermes plugins list | grep loom
```

### 行為驗證

| 項目 | 驗證方式 | 預期結果 |
|------|---------|---------|
| pre_llm_call LOOM 注入 | 檢查 session log 是否含 LOOM context | 有 context |
| pre_llm_call Y 跳過 | LOOM 活躍時 Y 不 inject | 僅 LOOM context |
| pre_tool_call 不過濾 read_file | 調用 read_file，無開銷 | log 無記錄 |
| pre_tool_call 觀察 write_file | 寫 tools/ 下新文件，不被 block | 新文件正常寫入 |
| post_tool_call 非工具不 solidify | 寫 /tmp/test.txt → 跳過 | KAFED 無新條目 |
| post_tool_call 新工具 solidify | 寫 tools/ 下含 registry.register() → 固化 | KAFED 有條目 | 
| post_tool_call 草稿不 solidify | 內容含 TODO → 跳過 | KAFED 無條目 |
| post_llm_call 不 heavy solidify | 每輪完成後 KAFED 不增加 | KAFED count 不變 |

## 參考

- [LOOM Architecture](loom-architecture.md) — LOOM 核心設計
- [YiCeNet Architecture](https://github.com/ahillzhao-msn/YiCeNet/blob/main/ARCHITECTURE.md) — YiCeNet 架構
- Hermes `hermes_cli/plugins.py` — VALID_HOOKS 定義與 invoke_hook 機制
- Hermes `agent/conversation_loop.py` — 實際調用 pre_llm_call / post_llm_call 的位置
- Hermes `model_tools.py` — 實際調用 pre_tool_call / post_tool_call 的位置
