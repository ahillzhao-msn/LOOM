# Pipeline Reference: 任務分解指南

**所屬**: KAFED Director  
**用途**: Pipeline「決」step 的思考參考——何時分解、如何分解、分解到多細。  
**定位**: 提示參考，非硬性流程。Agent/Director 在「決」step 時載入，結合自身判斷使用。  
**擴展性**: 可複寫、可擴展。其他項目可複製此文件並修改分解規則，不影響 KAFED 核心邏輯。

---

## 一、分解判斷樹

### 判斷起點：EVAL F1（範圍）

```
F1 = 1（trivial）
  └─ 零子任務，不分解，直接回答
  └─ 例：查一個 T-Code、回一個記憶中的事實

F1 = 2（moderate）
  ├─ 可拆：2-4 個子任務，一次響應內完成
  └─ 不可拆：任務本身原子性（如「翻譯這段文字」）

F1 = 3（complex）
  ├─ 需研究：先做探索（web search / KAFED 查詢 / 讀文檔）
  │   └─ 探索結果在下輪或同輪完成分解
  └─ 技術可行但不拆：任務雖大但線性不可分（如「寫一篇連續文章」）
```

### 輔助信號

| 信號 | 指示 |
|------|------|
| 知識召回發現多個獨立領域 | 可拆 |
| YiCeNet 卦象穩定（連續相同） | 高置信，可拆 |
| 卦象跳躍（d>5） | 不穩定，先研究再拆 |
| 用戶明確說「一步一步來」 | 拆 |
| 用戶說「直接做」 | 收斂不拆 |

---

## 二、分解邊界（多細）

### 三個自然邊界

1. **平行邊界** — 能同時跑的任務拆開  
   - 例：同時查兩個不同的 BAPI 文檔 → 兩個子任務並行

2. **產物邊界** — 上一步輸出是下一步輸入  
   - 例：研究 FM 簽名 → 寫調用代碼 → 審查結果  
   - 依賴鏈：A → B → C

3. **模型邊界** — 需要不同能力/不同模型  
   - 例：推理密集型（leader） + 代碼生成（md1） + 格式化（sm1）  
   - 每種能力匹配不同模型

### 粗細守則

```
太細（over-decomposition）:
  DEFINE → SELECT → LOOP → WRITE → FORMAT → TEST
  每步 2 行代碼 → DAG 開銷 > 執行收益 ✗

合理（sweet spot）:
  研究FM簽名 → 寫核心邏輯 → 審查 + 格式化
  每步 20-50 工具調用 → 值得 delegate_task ✓

太粗（under-decomposition）:
  寫整個報表（永不分解） → 等於沒用 DAG ✗
```

**經驗法則**：一個子任務最少應該值得一個 `delegate_task` 的啟動成本（~2K tokens）。如果一個步驟只需 2-3 個工具調用，就不要拆。

---

## 三、分解產出格式

每輪「決」step 產出一個清單：

```python
subtasks = [
    {
        "id": "research",
        "description": "研究 BAPI_PROGRAMMING_GETLIST 簽名和用法",
        "depends_on": [],           # 無依賴 → 可並行
        "estimated_tokens": 8000,   # 提供給 Finder 做 context_window 匹配
    },
    {
        "id": "write_code",
        "description": "寫 ABAP 報表核心邏輯",
        "depends_on": ["research"], # 依賴 research 完成
        "estimated_tokens": 16000,
    },
    {
        "id": "review",
        "description": "審查代碼完整性 + 格式化輸出",
        "depends_on": ["write_code"],
        "estimated_tokens": 4000,
    },
]
```

然後：
```
results = get_router().find_partners(
    briefs=[st["description"] for st in subtasks],
    budget="free",          # 總體預算控制
    prefer_local=True,
    top_k=1,
)
```

每個 `results[i]` 的 `best()` 即為該子任務的匹配模型。

---

## 四、終審（Agent 保留最終決定權）

Finder 返回後，Agent 逐項審查：

```
高置信 (>0.7):    直接接受 Finder 建議
中等置信 (0.4-0.7): 考慮自己幹（當前模型就是 Agent 自己）
低置信 (<0.4):     自己幹，或回爐 refine task description
```

如果 Agent 選擇自己執行某個子任務，它在當前的上下文裡直接完成，不委託給 `delegate_task`。

---

## 五、不分解的場景

以下情況即使 F1>=2 也不分解：

- **用戶期望單一回應**：「給我一段完整的代碼」
- **任務本質連續**：翻譯、潤色、一體化設計
- **上下文不可分割**：需要在同一段思考中完成推理
- **快速迭代**：修改/除錯場景，直接在當前上下文改更快

判斷標準：**分解後的通信開銷是否超過分解的收益。**

---

## 六、擴展指南

其他項目如需自訂分解規則：

1. 複製此文件到項目自有路徑
2. 修改「分解邊界」「判斷樹」「不分解場景」等章節
3. 在 Pipeline「決」step 中載入自訂版本而非默認版本

KAFED 不強制任何分解策略。此指南是**參考**，不是規則引擎。
