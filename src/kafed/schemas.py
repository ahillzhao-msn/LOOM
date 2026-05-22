"""
知识分类枚举体系（移植自 knowledge_item.py）。

用于标注向量库中的 metadata，支持 RAG 结果按类型过滤。
"""
from __future__ import annotations

from enum import Enum


class KnowledgeLevel(str, Enum):
    """知识层级 — 从通用到公司特化。
    
    用于 metadata 标注，辅助 RAG 结果优先级排序。
    """
    L1 = "L1"  # 语言/平台基础：语法、架构、系统限制
    L2 = "L2"  # 模块功能：PM通知、VC配置
    L3 = "L3"  # 业务/流程：从申请到竣工的完整流程
    L4 = "L4"  # 公司特化：操作码含义、在地惯例


class KnowledgeType(str, Enum):
    """知识类型 — 从事实到经验。
    
    用于 RAG 上下文装配时的类型匹配。
    """
    DECLARATIVE = "declarative"    # 声明型：事实、定义
    PROCEDURAL = "procedural"      # 程序型：步骤、流程
    REASONING = "reasoning"        # 推理型：原理、因果
    EXPERIENTIAL = "experiential"  # 经验型：教训、陷阱


class SourceType(str, Enum):
    """知识来源类型。"""
    LOCAL_DOC = "local_doc"  # 本地文档 (PDF/DOCX/PPTX)
    WEB = "web"              # 网页
    WIKI = "wiki"            # 已有 wiki 页面
    DIRECT = "direct"        # 直接摄入（文本/API）
