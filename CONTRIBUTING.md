# 贡献指南

## 代码风格

- 使用 Black 进行格式化
- 使用 isort 进行排序
- 使用 type hints 添加类型提示
- 遵循 PEP 8 规范

## PR 流程

1. 创建 feature branch，从 master 分支分叉
2. 提交代码修改
3. 在 feature branch 上运行测试
4. 将 code 合并至 master
5. 使用 squash merge 合并不所有 commit
6. 添加相关文档和注释

## 测试要求

- 所有代码必须通过 pytest tests/ 中的测试
- 新增功能需包含对应的 test 文件
- 测试失败时不得提交代码

## 设计原则

1. **先审后动** — 重大变更需经过设计审查
2. **质量第一** — 宁慢勿脏，优先保障稳定性
3. **干净解耦** — 保持代码结构清晰可读
4. **文档完整** — 每个功能点都必须有说明
5. **测试覆盖** — 新增功能需包含测试

## 提交规范

- 每次提交只修改一个文件
- 添加注释和文档的 commit 不要合并到 master
- 使用 git rebase -i 进行 squash merge
