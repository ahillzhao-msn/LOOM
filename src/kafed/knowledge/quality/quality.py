"""
质量管控模块 — 文档片段质量检测。

移植自旧 knowledge-management 技能的精华:
  - gates.py: 格式门/内容门/质量门（PDF伪影/重复/截断/URL占比）
  - sft-preprocessor.py: 噪声模式(15项) / 领域术语密度 / quality_score 公式

所有函数为纯函数，无副作用，可独立测试。
"""
from __future__ import annotations

import re
from typing import Any

# ── 噪声模式（移植自 sft-preprocessor.py） ──────────────
# 覆盖 PDF 转换、OCR、网页抓取的常见伪影
NOISE_PATTERNS: list[tuple[str, str]] = [
    # 图片/占位符
    (r'\*\*==> picture .*? <==\*\*', ''),
    (r'<!-- image -->', ''),
    (r'!\[.*?\]\(.*?\)', ''),           # markdown 图片
    # 页码/页眉
    (r'^Page \d+.*$', ''),
    (r'^第\s*\d+\s*页.*$', ''),
    (r'^\d+$', ''),                     # 孤立页码行
    # 版权/法律声明
    (r'^Copyright .*$', ''),
    (r'^All [Rr]ights [Rr]eserved.*$', ''),
    (r'^No part of this publication.*$', ''),
    (r'^Printed in .*$', ''),
    (r'^\d{4} SAP (AG|SE|Press).*$', ''),
    (r'^Published by .*$', ''),
    (r'^Copy No\..*$', ''),
    (r'^For personal use of.*$', ''),
    (r'This E-Bite is protected by copyright.*$', ''),
    # HTML 伪影（doc2md 转换残留）
    (r'<br\s*/?>', ' '),                # HTML 换行 → 空格
    (r'<[^>]+>', ''),                   # 其他 HTML 标签
    (r'&[a-z]+;', ' '),                # HTML 实体 &nbsp; &amp; 等
    (r'\|®\s*\|?', ' '),              # SAP Press 表格注册商标伪影
    (r'\|\|', '|'),                     # 空表格列
    (r'\[®\s*\]', ''),                 # [®] 伪影
    (r'©\s*\d{4}\s+SAP', ''),          # SAP 版权行
    # PDF 表格/文档转换残留
    (r'\[«\]', ''),                      # table of contents 箭头
    (r'\[®\s*\]?', ''),                  # [®] 或 ®
    (r'\[—\]', ''),                      # 表格破折号
    (r'\[hold\]', ''),                   # 表格占位符
    (r'\[still\]', ''),                  # OCR 残留
    # pymupdf4llm 表格转换 → 单词包裹在方括号里 [word]
    (r'\[([a-z][a-z\-]+)\]', r'\1'),    # 去掉小写单词的方括号，保留单词
    (r'\[([a-z])\]', r'\1'),            # 单字母 [a] [b] 同理
    (r'\[([A-Z])\]', r'\1'),            # 大写单字母 [E] [M]
    (r'\[([A-Z][a-z]+)\]', r'\1'),      # [The] [You] [Items] → 保留内容
    (r'\[([A-Z0-9]+)\]', r'\1'),        # [ABAP] [M1] → 保留内容
    (r'\[(\d+\.\d+)\]', r'\1'),          # [5.1] [5.7] → 无括号
    (r'\[(\w+\.)\]', r'\1'),             # [No.] → 无括号
    # 连字修复
    (r'\ufb00', 'ff'),
    (r'\ufb01', 'fi'),
    (r'\ufb02', 'fl'),
    (r'\ufb03', 'ffi'),
    (r'\ufb04', 'ffl'),
    # 多余空行
    (r'\n{4,}', '\n\n'),
]

# ── SAP 领域术语模式（移植自 sft-preprocessor.py） ──────
SAP_TERM_PATTERN = re.compile(
    r'\b(IW\d{2}|CT\d{2}|CU\d{2}|MM\d{2}|SE\d{2}|SM\d{2}|'
    r'VA\d{2}|ME\d{2}|FB\d{2}|F\-|PLM\d{3}|SCM\d{3}|'
    r'SAP|ABAP|BAPI|RFC|IDoc|BAdI|ALV|Fiori|S/4HANA)\b',
    re.IGNORECASE
)

# ── 通用术语密度模式（非 SAP 领域） ─────────────────────
GENERAL_TERM_PATTERN = re.compile(
    r'\b(maintenance|configuration|workflow|notification|order|'
    r'process|system|method|function|implementation|interface|'
    r'definition|parameter|schema|protocol|standard|version)\b',
    re.IGNORECASE
)


def clean_text(text: str) -> str:
    """应用所有噪声模式清洗文本。"""
    for pattern, replacement in NOISE_PATTERNS:
        text = re.sub(pattern, replacement, text, flags=re.MULTILINE)
    return text.strip()


# ── 格式门 ──────────────────────────────────────────────

def check_format(content: str) -> dict:
    """格式门：检查内容的基本结构要求。

    RAG chunks 可以短至 50 字符（含领域术语）。
    Returns:
        {"pass": bool, "reason": str | None}
    """
    if len(content) < 50:
        return {"pass": False, "reason": "too_short"}
    return {"pass": True, "reason": None}


# ── 内容门 ──────────────────────────────────────────────

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
        # 如果去除 frontmatter 后空空如也
        body = re.sub(r'^---\n.*?\n---\n', '', content, flags=re.DOTALL).strip()
        if len(body) < 100:
            return {"pass": False, "reason": "frontmatter_only"}

    return {"pass": True, "reason": None}


# ── 质量门 ──────────────────────────────────────────────

def assess_quality(content: str) -> dict:
    """质量门：综合评估文档片段质量。

    Returns:
        {
            "score": float (0.0-1.0),
            "issues": list[str],
            "density": float,
            "noise_ratio": float,
        }
    """
    issues = []

    # PDF 伪影：单词间双空格
    if re.search(r'(\w)\s{2,}(\w)', content):
        issues.append("pdf_artifact")

    # 重复行检测
    lines = content.split('\n')
    line_set = set()
    rep_count = 0
    for line in lines:
        line = line.strip()
        if len(line) > 20:
            if line in line_set:
                rep_count += 1
            else:
                line_set.add(line)
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

    # 空行比检测
    total_lines = len(lines)
    content_lines = sum(1 for l in lines if len(l.strip()) > 20)
    noise_ratio = (total_lines - content_lines) / max(total_lines, 1)
    if noise_ratio > 0.7:
        issues.append("high_noise_ratio")

    # 质量分
    score = max(0.0, 1.0 - len(issues) * 0.2)

    return {
        "score": round(score, 3),
        "issues": issues,
        "score_no_issues": score >= 0.6,
    }


def compute_domain_density(text: str) -> float:
    """计算领域术语密度（术语数/100 chars）。

    同时检查 SAP 术语和通用技术术语。
    Returns:
        {"sap_density": float, "general_density": float, "combined": float}
    """
    sap_terms = SAP_TERM_PATTERN.findall(text)
    general_terms = GENERAL_TERM_PATTERN.findall(text)
    length = len(text)
    if length == 0:
        return 0.0
    return min(5.0, (len(sap_terms) + len(general_terms) * 0.3) / length * 100)


# ── 综合质量评分 ────────────────────────────────────────

def compute_quality_score(content: str, domain: str | None = None) -> dict:
    """综合质量评分。

    公式（移植自 sft-preprocessor.py 并增强）:
        score = 0.3 + density * 0.3 + min(len, 2000)/2000 * 0.2
        - 调整: issues penalty

    Returns:
        {
            "score": float (0.0-1.0),
            "is_usable": bool (score >= 0.5),
            "issues": list[str],
            "density": float,
            "chars": int,
        }
    """
    # 基础分（移植自 sft-preprocessor.py 公式并微调）
    # 原公式: quality = 0.3 + density * 0.3 + min(len,2000)/2000 * 0.2
    density = compute_domain_density(content)
    length_factor = min(len(content), 2000) / 2000
    base_score = 0.3 + density * 0.25 + length_factor * 0.2

    # 质量门检查
    quality = assess_quality(content)
    penalty = len(quality["issues"]) * 0.15
    final_score = max(0.0, min(1.0, base_score - penalty))

    return {
        "score": round(final_score, 3),
        "is_usable": final_score >= 0.5,
        "issues": quality["issues"],
        "density": round(density, 2),
        "chars": len(content),
    }


# ── 去重（简化版，不依赖 wiki） ─────────────────────────

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
