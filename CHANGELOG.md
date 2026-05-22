# KAFED 版本历史

## v2.0.0 (2026-05-22)

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
