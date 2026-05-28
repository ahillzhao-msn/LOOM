"""KAFED Analyzer — 离线一般性知识库稽核。

與 AuditEngine 的分工：
  AuditEngine  → 任務驅動。比較意圖 vs 執行，生成反饋。
  KbAuditor    → 知識庫驅動。獨立檢查整體知識健康度。

稽核維度（按優先級）：
  1. 領域健康度 — 分佈平衡、異常值、空域
  2. 質量掃描 — 噪聲檢測、短條目、異常模式
  3. 新鮮度 — 過時條目標記、冷域
  4. 一致性 — 重複檢測、孤兒條目嫌疑
  5. 覆蓋率 — 會話中討論但知識庫沒有的領域

所有 check 是可註冊的 KbCheck，規則化（同 AuditRule 模式）。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import numpy as np

from kafed.config import get_config
from kafed.knowledge.rag.vector_store import VectorStore

logger = logging.getLogger("kafed.analyzer.kb_audit")


# ── 稽核結果數據結構 ──────────────────────────


@dataclass
class KbIssue:
    """一條知識庫問題。"""
    category: str          # domain_health | quality | freshness | consistency | coverage
    severity: str          # critical | warning | info
    domain: str = ""
    description: str = ""
    details: dict = field(default_factory=dict)
    suggestion: str = ""


@dataclass
class KbAuditReport:
    """知識庫稽核報告。"""
    timestamp: str = ""
    total_chunks: int = 0
    total_domains: int = 0
    domains: dict[str, dict] = field(default_factory=dict)  # domain → stats
    issues: list[KbIssue] = field(default_factory=list)
    health_score: float = 1.0      # 0.0~1.0
    summary: str = ""


# ── Check 註冊系統 ────────────────────────────


@dataclass
class KbCheck:
    """一條可註冊的知識庫稽核檢查。

    run(inspector) 返回 KbIssue 列表。
    """
    name: str
    description: str = ""
    category: str = "domain_health"
    enabled: bool = True
    run: Callable = lambda self, ins: []  # (KbInspector) → list[KbIssue]
    priority: int = 10


class KbInspector:
    """知識庫檢查器——提供 VectorStore 訪問 + 各類分析工具。"""

    def __init__(self, store: VectorStore | None = None):
        self.cfg = get_config()
        self.store = store or VectorStore()
        self._all_data: dict | None = None  # 惰性加載

    # ── 數據訪問 ──────────────────────────────

    def all_data(self) -> dict:
        """全量數據（惰性加載，只跑一次）。"""
        if self._all_data is None:
            self._all_data = self.store.get_all(limit=100_000)
        return self._all_data

    def domain_stats(self) -> dict[str, dict]:
        """返回 {domain: {count, avg_len, ...}}。"""
        data = self.all_data()
        metadatas = data.get("metadatas", []) or []
        documents = data.get("documents", []) or []
        ids = data.get("ids", []) or []

        stats: dict[str, dict] = {}
        for i, meta in enumerate(metadatas):
            domain = (meta.get("domain", "UNKNOWN")
                      if isinstance(meta, dict) else "UNKNOWN")
            if domain not in stats:
                stats[domain] = {
                    "count": 0,
                    "total_len": 0,
                    "sources": set(),
                    "sample_ids": [],
                }
            stats[domain]["count"] += 1
            doc = documents[i] if i < len(documents) else ""
            stats[domain]["total_len"] += len(str(doc))
            src = meta.get("source", "") if isinstance(meta, dict) else ""
            stats[domain]["sources"].add(str(src))
            if len(stats[domain]["sample_ids"]) < 3:
                stats[domain]["sample_ids"].append(ids[i] if i < len(ids) else "")

        # 計算平均長度
        for d in stats:
            stats[d]["avg_len"] = (
                stats[d]["total_len"] / stats[d]["count"]
                if stats[d]["count"] > 0 else 0
            )
            stats[d]["sources"] = sorted(stats[d]["sources"])

        return stats

    def sample_chunks(self, domain: str, n: int = 5) -> list[dict]:
        """從指定域隨機取樣 chunks。"""
        data = self.store.get_by_domain(domain, limit=n) if domain else {"ids": []}
        out = []
        ids = data.get("ids", []) or []
        docs = data.get("documents", []) or []
        metas = data.get("metadatas", []) or []
        for i in range(min(n, len(ids))):
            out.append({
                "id": ids[i],
                "content": str(docs[i])[:200] if i < len(docs) else "",
                "meta": metas[i] if i < len(metas) else {},
            })
        return out

    def detect_noise(self, text: str) -> list[str]:
        """檢測文本中的噪聲模式。"""
        patterns = []
        # URL/郵件
        if re.search(r'https?://\S+', text):
            patterns.append("contains_url")
        if re.search(r'[\w.+-]+@[\w-]+\.[\w.]+', text):
            patterns.append("contains_email")
        # 亂碼（高比例非ASCII）
        if text:
            non_ascii = sum(1 for c in text if ord(c) > 127)
            if len(text) > 50 and non_ascii / len(text) > 0.8:
                patterns.append("likely_garbled")
        # 極短
        if len(text) < 20:
            patterns.append("too_short")
        # 表格殘留
        if re.search(r'─{3,}|━{3,}|═{3,}', text):
            patterns.append("table_artifact")
        return patterns


# ── 內置 Checks ──────────────────────────────


def _check_domain_health(ins: KbInspector) -> list[KbIssue]:
    """領域健康度：分佈、空域、極端偏斜。"""
    issues: list[KbIssue] = []
    stats = ins.domain_stats()

    total = sum(s["count"] for s in stats.values())
    if total == 0:
        issues.append(KbIssue(
            category="domain_health", severity="critical",
            description="知識庫為空——沒有任何 chunk",
            suggestion="執行批量攝入管道",
        ))
        return issues

    # 空域或極小域 (< 5 chunks)
    for domain, s in sorted(stats.items(), key=lambda x: x[1]["count"]):
        if s["count"] < 5:
            issues.append(KbIssue(
                category="domain_health", severity="warning",
                domain=domain,
                description=f"域「{domain}」僅 {s['count']} 個 chunk，可能覆蓋不足",
                details={"count": s["count"], "sources": s["sources"]},
                suggestion="補充該領域文檔後重新攝入",
            ))

    # 單域佔比過高 (> 50%)
    for domain, s in stats.items():
        ratio = s["count"] / total
        if ratio > 0.50:
            issues.append(KbIssue(
                category="domain_health", severity="warning",
                domain=domain,
                description=f"域「{domain}」佔 {ratio:.0%}，可能偏斜",
                details={"count": s["count"], "total": total, "ratio": ratio},
                suggestion="均衡各域攝入量",
            ))

    return issues


def _check_quality(ins: KbInspector) -> list[KbIssue]:
    """質量掃描：採樣檢查噪聲。"""
    issues: list[KbIssue] = []
    stats = ins.domain_stats()

    for domain in stats:
        samples = ins.sample_chunks(domain, n=10)
        noise_count = 0
        noise_types: set[str] = set()
        for s in samples:
            patterns = ins.detect_noise(s.get("content", ""))
            if patterns:
                noise_count += 1
                noise_types.update(patterns)

        if noise_count > len(samples) * 0.5:
            issues.append(KbIssue(
                category="quality", severity="critical",
                domain=domain,
                description=f"域「{domain}」樣本 {noise_count}/{len(samples)} 含噪聲",
                details={"noise_count": noise_count, "sample_size": len(samples),
                         "noise_types": sorted(noise_types)},
                suggestion="重新提取或清洗該域文檔",
            ))
        elif noise_count > 0:
            issues.append(KbIssue(
                category="quality", severity="warning",
                domain=domain,
                description=f"域「{domain}」樣本 {noise_count}/{len(samples)} 含噪聲",
                details={"noise_count": noise_count, "sample_size": len(samples),
                         "noise_types": sorted(noise_types)},
                suggestion="檢查該域來源文檔質量",
            ))

    # 極短條目全域掃描
    data = ins.all_data()
    docs = data.get("documents", []) or []
    short_count = sum(1 for d in docs if len(str(d)) < 20)
    total = len(docs)
    if short_count > 0:
        severity = "critical" if short_count > total * 0.1 else "warning"
        issues.append(KbIssue(
            category="quality", severity=severity,
            description=f"{short_count}/{total} 條目少於 20 字符",
            details={"short_count": short_count, "total": total},
            suggestion="過濾或補全短條目",
        ))

    return issues


def _check_freshness(ins: KbInspector) -> list[KbIssue]:
    """新鮮度：檢查條目的時間戳。"""
    issues: list[KbIssue] = []
    data = ins.all_data()
    metadatas = data.get("metadatas", []) or []
    docs = data.get("documents", []) or []
    ids = data.get("ids", []) or []

    now = datetime.now(timezone.utc)
    stale_count = 0
    stale_domains: dict[str, int] = {}

    for i, meta in enumerate(metadatas):
        if not isinstance(meta, dict):
            continue
        ts_str = meta.get("timestamp", "")
        if not ts_str:
            continue
        try:
            ts = datetime.fromisoformat(ts_str)
            days_old = (now - ts).days
            if days_old > 90:
                stale_count += 1
                domain = meta.get("domain", "UNKNOWN")
                stale_domains[domain] = stale_domains.get(domain, 0) + 1
        except (ValueError, TypeError):
            continue

    if stale_count > 0:
        worst_domain = max(stale_domains, key=stale_domains.get)
        issues.append(KbIssue(
            category="freshness", severity="warning",
            description=f"{stale_count} 條目超過 90 天（最多在 {worst_domain}）",
            details={"stale_count": stale_count, "by_domain": stale_domains},
            suggestion="考慮重新攝入過時域",
        ))

    return issues


def _check_consistency(ins: KbInspector) -> list[KbIssue]:
    """一致性：重複檢測、異常域。"""
    issues: list[KbIssue] = []
    data = ins.all_data()
    docs = data.get("documents", []) or []
    ids = data.get("ids", []) or []
    metadatas = data.get("metadatas", []) or []

    # 近似重複：前50字符相同
    seen_prefixes: dict[str, list[str]] = {}
    for i, doc in enumerate(docs):
        prefix = str(doc)[:50].strip().lower()
        if len(prefix) > 10:
            if prefix not in seen_prefixes:
                seen_prefixes[prefix] = []
            seen_prefixes[prefix].append(ids[i] if i < len(ids) else f"#{i}")

    dup_count = 0
    for prefix, dups in seen_prefixes.items():
        if len(dups) > 1:
            dup_count += len(dups) - 1

    if dup_count > 0:
        issues.append(KbIssue(
            category="consistency", severity="warning",
            description=f"檢測到 {dup_count} 個近似重複條目",
            details={"duplicate_count": dup_count, "total": len(docs)},
            suggestion="運行 KAFED 去重指令",
        ))

    # 異常域名（含空格、非底線大寫字母）
    # UPPER_SNAKE_CASE 如 SAP_PM/ABAP 是合規範的
    stats = ins.domain_stats()
    suspicious_domains = [
        d for d in stats if re.search(r'\s', d) or (
            re.search(r'[A-Z]', d) and not re.match(r'^[A-Z][A-Z_]*$', d)
        )
    ]
    for d in suspicious_domains:
        issues.append(KbIssue(
            category="consistency", severity="info",
            domain=d,
            description=f"域名「{d}」含空格或大寫，規範應為大寫底線",
            details={"count": stats[d]["count"]},
            suggestion="重新分類該域條目",
        ))

    return issues


def _check_coverage(ins: KbInspector) -> list[KbIssue]:
    """覆蓋率：知識庫是否有常見空白域。"""
    issues: list[KbIssue] = []
    stats = ins.domain_stats()
    total = sum(s["count"] for s in stats.values())
    if total < 50:
        issues.append(KbIssue(
            category="coverage", severity="info",
            description=f"知識庫較小（{total} chunks），覆蓋率評估不充分",
            suggestion="持續攝入到 500+ chunks 後再評估覆蓋率",
        ))
    return issues


# ── 默認檢查列表 ──────────────────────────────

DEFAULT_CHECKS: list[KbCheck] = [
    KbCheck(
        name="domain_health",
        description="領域分佈健康度：空域、偏斜、極小域",
        category="domain_health",
        run=_check_domain_health,
        priority=10,
    ),
    KbCheck(
        name="quality_scan",
        description="質量掃描：噪聲、短條目、異常模式",
        category="quality",
        run=_check_quality,
        priority=20,
    ),
    KbCheck(
        name="freshness",
        description="新鮮度：90天過時條目",
        category="freshness",
        run=_check_freshness,
        priority=30,
    ),
    KbCheck(
        name="consistency",
        description="一致性：重複、域名規範",
        category="consistency",
        run=_check_consistency,
        priority=40,
    ),
    KbCheck(
        name="coverage",
        description="覆蓋率：知識庫完整性",
        category="coverage",
        run=_check_coverage,
        priority=50,
    ),
]


# ── KbAuditor ─────────────────────────────────


class KbAuditor:
    """知識庫稽核器——離線一般性稽核。

    用法：
        auditor = KbAuditor()
        report = auditor.audit()
        print(report.summary)

        # 註冊自定義檢查
        auditor.register_check(KbCheck(
            name="custom_check", run=my_fn, ...
        ))
    """

    def __init__(self, store: VectorStore | None = None):
        self._checks: list[KbCheck] = list(DEFAULT_CHECKS)
        self._inspector = KbInspector(store)

    # ── 檢查管理 ──────────────────────────────

    def register_check(self, check: KbCheck) -> None:
        for i, c in enumerate(self._checks):
            if c.name == check.name:
                self._checks[i] = check
                logger.info("KB check 已更新: %s", check.name)
                return
        self._checks.append(check)
        self._checks.sort(key=lambda c: c.priority)
        logger.info("KB check 已註冊: %s (prio=%d)", check.name, check.priority)

    def unregister_check(self, name: str) -> bool:
        old_len = len(self._checks)
        self._checks = [c for c in self._checks if c.name != name]
        return len(self._checks) < old_len

    def list_checks(self) -> list[dict]:
        return [
            {"name": c.name, "category": c.category,
             "priority": c.priority, "enabled": c.enabled,
             "description": c.description}
            for c in self._checks
        ]

    def enable_check(self, name: str, enabled: bool) -> bool:
        for c in self._checks:
            if c.name == name:
                c.enabled = enabled
                return True
        return False

    # ── 主要入口 ──────────────────────────────

    def audit(self) -> KbAuditReport:
        """執行一次完整的知識庫稽核。"""
        report = KbAuditReport()
        report.timestamp = datetime.now(timezone.utc).isoformat()

        # 先獲取基本信息
        try:
            stats = self._inspector.domain_stats()
            report.domains = {
                d: {
                    "count": s["count"],
                    "avg_len": s["avg_len"],
                    "sources": s["sources"],
                }
                for d, s in stats.items()
            }
            report.total_chunks = sum(s["count"] for s in stats.values())
            report.total_domains = len(stats)
        except Exception as e:
            logger.error("KB 統計失敗: %s", e)
            report.issues.append(KbIssue(
                category="domain_health", severity="critical",
                description=f"無法讀取知識庫: {e}",
            ))
            report.health_score = 0.0
            report.summary = "知識庫讀取失敗"
            return report

        # 逐檢查執行
        for check in self._checks:
            if not check.enabled:
                continue
            try:
                issues = check.run(self._inspector)
                report.issues.extend(issues)
            except Exception as e:
                logger.warning("KB check %s 失敗: %s", check.name, e)
                report.issues.append(KbIssue(
                    category=check.category, severity="warning",
                    description=f"檢查 {check.name} 執行失敗: {e}",
                ))

        # 計算健康度
        report.health_score = self._calc_health(report)

        # 生成摘要
        report.summary = self._build_summary(report)

        # 寫日誌
        self._log_report(report)

        return report

    # ── 內部 ──────────────────────────────────

    def _calc_health(self, report: KbAuditReport) -> float:
        """從問題推導健康度評分。"""
        if report.total_chunks == 0:
            return 0.0
        critical = sum(1 for i in report.issues if i.severity == "critical")
        warning = sum(1 for i in report.issues if i.severity == "warning")
        info = sum(1 for i in report.issues if i.severity == "info")
        score = 1.0 - (critical * 0.15 + warning * 0.05 + info * 0.01)
        return max(0.0, min(1.0, score))

    def _build_summary(self, report: KbAuditReport) -> str:
        parts = [f"KB稽核: {report.total_chunks} chunks, {report.total_domains} 域"]
        parts.append(f"健康度: {report.health_score:.2f}")
        by_sev = {"critical": 0, "warning": 0, "info": 0}
        for i in report.issues:
            by_sev[i.severity] = by_sev.get(i.severity, 0) + 1
        if by_sev["critical"]:
            parts.append(f"嚴重⚠ {by_sev['critical']}")
        if by_sev["warning"]:
            parts.append(f"警告⚡ {by_sev['warning']}")
        if by_sev["info"]:
            parts.append(f"提示ℹ {by_sev['info']}")
        return " | ".join(parts)

    def _log_report(self, report: KbAuditReport) -> None:
        log_dir = self._cfg().data_dir / "kb_audit_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        log_file = log_dir / f"kb_audit_{today}.jsonl"

        entry = {
            "timestamp": report.timestamp,
            "total_chunks": report.total_chunks,
            "total_domains": report.total_domains,
            "health_score": report.health_score,
            "issue_count": len(report.issues),
            "by_severity": {
                "critical": sum(1 for i in report.issues if i.severity == "critical"),
                "warning": sum(1 for i in report.issues if i.severity == "warning"),
                "info": sum(1 for i in report.issues if i.severity == "info"),
            },
            "summary": report.summary,
        }
        with open(log_file, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        logger.info(report.summary)

    @staticmethod
    def _cfg():
        return get_config()
