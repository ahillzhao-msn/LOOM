# KAFED 版本历史

## v2.2.0 (2026-05-26)

### 新增功能
- **Bootstrap 安裝系統**: 7 階段自動環境初始化（env 檢測 → config 生成 → Chroma 初始化 → cron → pip 安裝 → YiCeNet 軟依賴 → 清理）
- **Finder v2 雙模路由**: `fast_route`（< 3 workers 時快速 CLI 發現）+ `full_route`（嵌入向量 + 上下文 + 狀態三維聚合匹配）
- **ContextProvider 預算感知召回**: budget-aware context injection，軟分類支持多 cluster 擴展搜索
- **Explorer 矩陣掃描**: 全量 Hermes 模型發現 + 模型能力維度標籤化，寫入 KAFED 向量存儲
- **Heartbeat v2**: async 指數衰減超時 + 心跳服務自動啟動
- **YiCeNet 軟依賴集成**: KAFED bootstrap Phase 6 自動 git clone + pip install + 檢查點 + cron，失敗繼續不中斷
- **kafed-bootstrap.sh**: 簡化 shell 封裝

### 架構改進
- 配置全局化: KafedSecrets（API key 隔離）+ KafedConfig（全部超參/路徑集中管理）
- Finder 三向量聚合: 子任務⊗模型⊗狀態，cosine similarity 匹配取代 field-by-field
- Executor DAGTask 新增 model_name/model_provider，dispatch_for() 注入 Finder 選擇
- ContextProvider 分層 hunting（Domain→Level→Type），超出三層仍模糊則接受
- data_dir 路徑 bug 修復（parent 層級數 4→3）
- kpak CLI: `__main__.py`（pack/unpack/list/info）+ `__init__.py` 暴露導出

### 文檔
- ARCHITECTURE.md: 7 章節全面架構文檔
- README.md 重寫: 英文優先 + badges + 正確 API 示例
- SOUL-template.md: 可分享的認知架構模板
- 新增: `.env.example`, `kafed.yaml.example`

### 清理
- SubTask/ExecutionReport 重複定義合併
- Backlog 統一單入口（`src/kafed/backlog.py`）
- Registry/roster.yaml 廢棄清理
- 舊 kpak 文件 (8 個) 刪除
- 舊 `kafed.server` 引用清除
- Finder WorkerManager 瘦身 1537→~350 行

## v2.1.0 (2026-05-23)

### 新增功能
- 六階層同構聚類（Entity + Registry 架構）
- `soft_classify` 模塊：top-1 vs top-2 分數差距 < 0.10 時自動多 cluster 擴展搜索
- Level 33 + Type 98 域名美化
- Centroid 飛輪 cron（每週日凌晨 3 點）
- ContextProvider 全源嵌入命中召回（RAG/Wiki/Memory/Sessions/Skills）

### 修復
- Memory 全量壓縮 21K→4.3K
- pulse_manager.py 刪除後 pulse-runner.sh 斷鏈修復
- 舊 cron 清理（flywheel_daily、centroid_rebuild 等）

### 新增功能
- 五层架构重构：Director/Finder/Executor/Analyzer/Knowledge
- 全局配置系统：引入 KafedConfig + KafedSecrets
- Executor 监督回馈环：实现自动状态监控和自检机制
- 流式可视化：FlowVisualizer 提供实时执行进度追踪
- 全局日志系统：KafedLogger 统一所有操作日志

### 架构改进
- Director 从任务调度器转变为全局状态监控者
- Finder 增加向量库权限管理和最佳匹配选择策略
- Analyzer 引入飞轮健康检查和异常模式识别
- Knowledge 层支持 Centroid 结构内化而非 raw weights

### 性能优化
- 移除硬编码定时任务，改用事件驱动非阈值机制
- 流式可视化减少人工监控负担
- 全局日志统一所有操作追踪

## v1.0.0 (2026-05-20)

### 初始版本
- KAFED 核心引擎初版
- Chromadb 向量库集成
- BGE-small RAG 引擎实现
- 基础推理逻辑框架

### 技术特性
- 基于向量数据的即时检索系统
- Centroid 结构内化数学概念
- 事件驱动非阈值任务执行
- MIT License 许可证

## 更新记录

本版本记录了所有重大变更和技术决策。请参考 README.md 获取详细架构说明。
