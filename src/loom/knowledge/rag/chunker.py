"""
文档分块模块 — 结构化分块 + 质量过滤。

输入: markdown 文本 → 输出: 高质量 chunk 列表

流程:
    1. 噪声清洗 (quality.clean_text)
    2. 按 ## 标题链分块 (移植自 sft-preprocessor)
    3. 超长块按段落拆分
    4. 质量评分过滤 (quality.compute_quality_score)
    5. 低于阈值的块丢弃

内部实现，零外部依赖。
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Iterator

from loom.config import get_config
from loom.knowledge.quality.quality import clean_text as q_clean, compute_quality_score


def chunk_document(text: str, domain: str | None = None,
                   max_chars: int | None = None) -> list[dict]:
    """
    将文档文本拆分为高质量块。

    返回:
        [{
            "id": str,
            "content": str,
            "heading": str | None,
            "heading_chain": list[str],
            "domain": str | None,
            "quality_score": float,
            "chars": int,
            "chunk_index": int,
        }, ...]
    """
    cfg = get_config()
    max_chars = max_chars or cfg.chunk_max_chars

    # Step 1: 噪声清洗
    cleaned = q_clean(text)
    if not cleaned.strip():
        return []

    # Step 2: 按 ## 标题分块（带标题链追踪）
    raw_chunks = _split_by_headings(cleaned)

    # Step 3: 超长块拆分
    split_chunks = _split_overlong(raw_chunks, max_chars)

    # Step 4: 质量评分 + 过滤
    result: list[dict] = []
    for i, (heading, content, heading_chain) in enumerate(split_chunks):
        qc = compute_quality_score(content, domain)
        if not qc["is_usable"]:
            continue

        chunk_id = hashlib.md5(
            f"{domain or ''}_{heading}_{content[:100]}".encode()
        ).hexdigest()[:16]

        result.append({
            "id": chunk_id,
            "content": content,
            "heading": heading,
            "heading_chain": heading_chain,
            "domain": domain or "",
            "quality_score": qc["score"],
            "quality_issues": qc["issues"],
            "chars": qc["chars"],
            "chunk_index": i,
        })

    return result


# ── 标题链分块（移植自 sft-preprocessor.py） ────────────

def _split_by_headings(text: str) -> list[tuple[str | None, str, list[str]]]:
    """按 ##/###/#### 标题分块，维护标题链。

    Returns: [(heading, content, heading_chain), ...]
    """
    chunks: list[tuple[str | None, str, list[str]]] = []
    lines = text.split('\n')
    current_section: list[str] = []
    current_heading: str | None = None
    heading_chain: list[str] = []
    section_start = 0

    for i, line in enumerate(lines):
        heading_match = re.match(r'^(#{2,4})\s+(.+)$', line)
        if heading_match:
            # 保存当前段
            if current_section and i > section_start:
                chunk_text = '\n'.join(current_section).strip()
                if chunk_text:
                    chunks.append((current_heading, chunk_text,
                                   list(heading_chain)))

            # 更新标题链
            level = len(heading_match.group(1))
            heading_text = heading_match.group(2).strip()

            if level == 2:
                heading_chain = [heading_text]
            elif level == 3 and heading_chain:
                heading_chain = heading_chain[:1] + [heading_text]
            elif level == 4 and len(heading_chain) >= 2:
                heading_chain = heading_chain[:2] + [heading_text]
            else:
                heading_chain.append(heading_text)

            current_heading = heading_text
            current_section = [line]
            section_start = i
        else:
            current_section.append(line)

    # 最后一段
    if current_section:
        chunk_text = '\n'.join(current_section).strip()
        if chunk_text:
            chunks.append((current_heading, chunk_text, list(heading_chain)))

    return chunks


# ── 超长块拆分 ──────────────────────────────────────────

def _split_overlong(
    chunks: list[tuple[str | None, str, list[str]]],
    max_chars: int,
) -> list[tuple[str | None, str, list[str]]]:
    """超过 max_chars 的块按段落拆分后合并不足 max_chars 的段。"""
    result: list[tuple[str | None, str, list[str]]] = []
    for heading, text, chain in chunks:
        if len(text) <= max_chars:
            result.append((heading, text, chain))
        else:
            # 按空行拆
            paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
            # 合并小段落
            merged = _merge_paragraphs(paragraphs, max_chars)
            for m in merged:
                result.append((heading, m, chain))
    return result


def _merge_paragraphs(paragraphs: list[str], max_chars: int) -> list[str]:
    """合并小段落成不超过 max_chars 的块。"""
    merged: list[str] = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) + 2 <= max_chars:
            current += ("\n\n" + para) if current else para
        else:
            if current:
                merged.append(current)
            current = para
    if current:
        merged.append(current)
    return merged
