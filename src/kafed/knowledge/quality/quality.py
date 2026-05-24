"""质量管控模块 — 文档片段质量检测。

域无关的通用质量信号，不依赖任何领域术语。
替代旧版 SAP 术语密度作为质量信号。

所有函数为纯函数，无副作用，可独立测试。
"""
from __future__ import annotations

import math
import re
from typing import Any

# ── 噪声模式 ──────────────────────────────────────
# 覆盖 PDF 转换、OCR、网页抓取的常见伪影
NOISE_PATTERNS: list[tuple[str, str]] = [
    # 图片/占位符
    (r'\*\*==> picture .*? <==\*\*', ''),
    (r'<!-- image -->', ''),
    (r'!\[.*?\]\(.*?\)', ''),               # markdown 图片
    # 页码/页眉
    (r'^Page \d+.*$', ''),
    (r'^第\s*\d+\s*页.*$', ''),
    (r'^\d+$', ''),                          # 孤立页码行
    # 版权/法律声明（通用版，不含特定公司名）
    (r'^Copyright .*$', ''),
    (r'^All [Rr]ights [Rr]eserved.*$', ''),
    (r'^No part of this publication.*$', ''),
    (r'^Printed in .*$', ''),
    (r'^Published by .*$', ''),
    (r'^Copy No\..*$', ''),
    (r'^For personal use of.*$', ''),
    # HTML 伪影（doc2md 转换残留）
    (r'<br\s*/?>', ' '),                     # HTML 换行 → 空格
    (r'<[^>]+>', ''),                        # 其他 HTML 标签
    (r'&[a-z]+;', ' '),                      # HTML 实体 &nbsp; &amp; 等
    # PDF 表格/文档转换残留
    (r'[«]', ''),                            # table of contents 箭头
    (r'[®]', ''),                            # 注册商标符号
    (r'[—]', ''),                            # 表格破折号
    (r'\[hold\]', ''),                       # 表格占位符
    (r'\[still\]', ''),                      # OCR 残留
    # pymupdf4llm 表格转换 → 单词包裹在方括号里 [word]
    (r'\[([a-z][a-z\-]+)\]', r'\1'),         # 去掉小写单词的方括号，保留单词
    (r'\[([a-z])\]', r'\1'),                  # 单字母 [a] [b] 同理
    (r'\[([A-Z])\]', r'\1'),                  # 大写单字母 [E] [M]
    (r'\[([A-Z][a-z]+)\]', r'\1'),            # [The] [You] [Items] → 保留内容
    (r'\[([A-Z0-9]+)\]', r'\1'),              # [ABAP] [M1] → 保留内容
    (r'\[(\d+\.\d+)\]', r'\1'),               # [5.1] [5.7] → 无括号
    (r'\[(\w+\.)\]', r'\1'),                  # [No.] → 无括号
    # 连字修复
    (r'\ufb00', 'ff'),
    (r'\ufb01', 'fi'),
    (r'\ufb02', 'fl'),
    (r'\ufb03', 'ffi'),
    (r'\ufb04', 'ffl'),
    # 多余空行
    (r'\n{4,}', '\n\n'),
]


def clean_text(text: str) -> str:
    """应用所有噪声模式清洗文本。"""
    for pattern, replacement in NOISE_PATTERNS:
        text = re.sub(pattern, replacement, text, flags=re.MULTILINE)
    return text.strip()


# ── 域无关的通用质量信号 ─────────────────────────

def compute_character_entropy(text: str) -> float:
    """字符级信息熵。越高 = 信息密度越大。

    纯重复文本（如 "aaaaaa"）熵低，多样化文本熵高。
    用 log2 計算，單位 bit/char。
    """
    if not text:
        return 0.0
    length = len(text)
    freq: dict[str, int] = {}
    for c in text:
        freq[c] = freq.get(c, 0) + 1
    entropy = 0.0
    for count in freq.values():
        p = count / length
        if p > 0:
            entropy -= p * math.log2(p)
    # 标准 ASCII 文本熵通常在 3.5-5.5 bit/char
    # 归一化到 0.0-1.0 (以 6.0 bit 为上限)
    return min(1.0, entropy / 6.0)


def compute_repetition_ratio(text: str) -> float:
    """重复行比例。检测模板化/样板内容。

    对长度 > 20 字符的行去重比较。
    返回 0.0-1.0，越高越糟糕。
    """
    lines = text.split('\n')
    long_lines = [l.strip() for l in lines if len(l.strip()) > 20]
    if not long_lines:
        return 0.0
    unique = set(long_lines)
    return 1.0 - len(unique) / len(long_lines)


def compute_structure_score(text: str) -> float:
    """结构丰富度。衡量段落/句子/列表的多样性。

    有段落间距、混合句式、列表结构的文本质量更高。
    返回 0.0-1.0。
    """
    score = 0.0
    if not text:
        return 0.0

    # 段落数（双换行分隔）
    paras = [p.strip() for p in text.split('\n\n') if p.strip()]
    para_count = len(paras)
    if para_count >= 3:
        score += 0.3
    elif para_count >= 2:
        score += 0.2
    elif para_count >= 1:
        score += 0.1

    # 句子数（句号/问号/感叹号）
    sentences = re.findall(r'[^。！？.!?]+[。！？.!?]', text)
    if len(sentences) >= 5:
        score += 0.3
    elif len(sentences) >= 3:
        score += 0.2

    # 有列举结构
    if re.search(r'^\s*[-*\d+.]\s+', text, re.MULTILINE):
        score += 0.2

    # 平均句长适中（非堆砌关键词）
    if sentences:
        avg_len = sum(len(s) for s in sentences) / len(sentences)
        if 20 <= avg_len <= 200:
            score += 0.2

    return min(1.0, score)


def compute_noise_ratio(text: str) -> float:
    """噪声行比例：空白行/短行占比。

    排除 markdown 標題（##, ### 等），它們是結構化標記而非噪聲。
    返回 0.0-1.0。
    """
    lines = text.split('\n')
    total = len(lines)
    if total == 0:
        return 0.0
    noise = 0
    for l in lines:
        stripped = l.strip()
        if not stripped:  # 空行是噪聲
            noise += 1
        elif len(stripped) <= 20 and not stripped.startswith('#'):
            # 短行但非 markdown 標題 → 噪聲
            noise += 1
    return noise / total


def compute_universal_signals(text: str) -> dict[str, float]:
    """计算所有通用质量信号。

    Returns:
        {
            "entropy": float (0-1),
            "repetition_ratio": float (0-1),
            "structure_score": float (0-1),
            "noise_ratio": float (0-1),
            "length_factor": float (0-1),
        }
    """
    return {
        "entropy": round(compute_character_entropy(text), 4),
        "repetition_ratio": round(compute_repetition_ratio(text), 4),
        "structure_score": round(compute_structure_score(text), 4),
        "noise_ratio": round(compute_noise_ratio(text), 4),
        "length_factor": round(min(len(text), 2000) / 2000, 4),
    }


# ── 格式门 ──────────────────────────────────────

def check_format(content: str) -> dict:
    """格式门：检查内容的基本结构要求。

    RAG chunks 可以短至 50 字符。
    Returns:
        {"pass": bool, "reason": str | None}
    """
    if len(content) < 50:
        return {"pass": False, "reason": "too_short"}
    return {"pass": True, "reason": None}


# ── 内容门 ──────────────────────────────────────

def check_content(content: str) -> dict:
    """内容门：必须有实质正文，非纯索引/目录/元数据。

    Returns:
        {"pass": bool, "reason": str | None}
    """
    if len(content) < 200:
        return {"pass": False, "reason": "too_short"}

    # 检查是否纯目录/索引
    first_line = content.strip().split('\n')[0].strip()
    if re.match(r'^(Table of Contents|目录|Index|索引|Contents|Overview)\s*$',
                first_line, re.I):
        return {"pass": False, "reason": "toc_only"}

    # 检查是否纯元数据（YAML frontmatter）
    if content.strip().startswith('---') and content.count('---') >= 2:
        body = re.sub(r'^---\n.*?\n---\n', '', content, flags=re.DOTALL).strip()
        if len(body) < 100:
            return {"pass": False, "reason": "frontmatter_only"}

    return {"pass": True, "reason": None}


# ── 质量门 ──────────────────────────────────────

def assess_quality(content: str) -> dict:
    """质量门：综合评估文档片段质量。

    Returns:
        {
            "score": float (0.0-1.0),
            "issues": list[str],
        }
    """
    issues = []

    # PDF 伪影：行内单词间双空格（不跨行）
    if re.search(r'(\w)[^\S\n]{2,}(\w)', content):
        issues.append("pdf_artifact")

    # 重复行检测
    lines = content.split('\n')
    line_set: set[str] = set()
    rep_count = 0
    for line in lines:
        line_s = line.strip()
        if len(line_s) > 20:
            if line_s in line_set:
                rep_count += 1
            else:
                line_set.add(line_s)
    if rep_count > 5:
        issues.append("repetition")

    # 截断检测
    stripped = content.rstrip()
    if stripped.endswith('...') or (stripped and len(stripped.split()[-1]) == 1):
        issues.append("truncated")

    # URL 占比检测
    urls = re.findall(r'https?://\S+', content)
    url_chars = sum(len(u) for u in urls)
    if content and url_chars / len(content) > 0.3:
        issues.append("url_dominated")

    # 空行比检测（排除 markdown 标题）
    total_lines = len(lines)
    content_lines = 0
    for l in lines:
        s = l.strip()
        if len(s) > 20 or s.startswith('#'):
            content_lines += 1
    noise_ratio = (total_lines - content_lines) / max(total_lines, 1)
    if noise_ratio > 0.7:
        issues.append("high_noise_ratio")

    score = max(0.0, 1.0 - len(issues) * 0.2)

    return {
        "score": round(score, 3),
        "issues": issues,
    }


# ── 综合质量评分 ─────────────────────────────────

def compute_quality_score(content: str, domain: str | None = None) -> dict:
    """综合质量评分。域无关，基于通用文本信号。

    公式:
        baseline = 0.3
        + structure * 0.25   (段落/句子结构)
        + entropy * 0.20     (信息密度)
        + length * 0.15      (长度因子)
        - repetition * 0.10  (重复惩罚)
        - noise * 0.10       (噪声惩罚)
        - issues_penalty     (质量门问题)

    Returns:
        {
            "score": float (0.0-1.0),
            "is_usable": bool (score >= 0.5),
            "issues": list[str],
            "signals": dict,      # 各信号原始值
            "chars": int,
        }
    """
    signals = compute_universal_signals(content)

    # 正向信号
    base = 0.3
    base += signals["structure_score"] * 0.25
    base += signals["entropy"] * 0.20
    base += signals["length_factor"] * 0.15

    # 负向信号
    base -= signals["repetition_ratio"] * 0.10
    base -= signals["noise_ratio"] * 0.10

    # 质量门问题惩罚
    quality = assess_quality(content)
    penalty = len(quality["issues"]) * 0.15

    final_score = max(0.0, min(1.0, base - penalty))

    return {
        "score": round(final_score, 3),
        "is_usable": final_score >= 0.5,
        "issues": quality["issues"],
        "signals": signals,
        "chars": len(content),
    }


# ── 去重（简化版，不依赖 wiki） ─────────────────

def compute_content_fingerprint(content: str, window: int = 200) -> str:
    """计算内容指纹（前 window 字符的 MD5）。"""
    import hashlib
    return hashlib.md5(content[:window].encode()).hexdigest()[:16]


def paragraphs_overlap(paragraphs_a: set[str],
                       paragraphs_b: set[str]) -> float:
    """计算两个段落集合的重叠率。"""
    if not paragraphs_a or not paragraphs_b:
        return 0.0
    overlap = len(paragraphs_a & paragraphs_b)
    return overlap / min(len(paragraphs_a), len(paragraphs_b))
