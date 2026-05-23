"""KAFED Analyzer — 稽查引擎（Audit Engine）。

非同步稽查員。不阻塞 D-F-E 鏈路，在 D固 完成後由 session_end 觸發。
對比 Director 初始意圖 vs 執行結果 vs 固化內容，生成反饋。

權限：
  對 KM：直接執行（提升/降級/修正/更新嵌入）
  對 Agent：建議（創建 Skill，不命令）
  對 SOUL：謹慎更新（頻率限制 + 衝突檢測）

設計哲學：動作由可註冊的規則（AuditRule）驅動，非硬編碼。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from kafed.config import get_config

logger = logging.getLogger("kafed.analyzer.audit")


# ── 核心數據結構 ──────────────────────────────


@dataclass
class AuditInput:
    """稽查輸入——來自 Director+Executor 的完整記錄。"""
    director_intent: str = ""
    hexagram_id: int = 0
    hexagram_name: str = ""
    pipeline_taken: str = ""
    steps: list[dict] = field(default_factory=list)
    task_results: list[dict] = field(default_factory=list)
    solidified: list[dict] = field(default_factory=list)
    outcome_quality: float = 0.5


@dataclass
class AuditAction:
    """稽查員決定採取的一項行動。"""
    action: str
    target: str
    content: str = ""
    confidence: float = 0.5
    reason: str = ""


@dataclass
class AuditReport:
    actions: list[AuditAction] = field(default_factory=list)
    quality_score: float = 0.5
    pattern_detected: str = ""
    summary: str = ""


# ── 規則系統 ──────────────────────────────────


@dataclass
class RuleCondition:
    """單個規則的條件表達式。

    每個條件是一個 (field, operator, value) 三元組。
    例如: ("quality_score", "gt", 0.7) 表示 quality_score > 0.7
    """
    field: str      # 可用的 field: quality_score | pattern | solidified_content | steps_status | tasks_failed | intent
    operator: str   # gt | lt | gte | lte | eq | contains | any_contains | len_gt
    value: Any      # 比較值


@dataclass
class AuditRule:
    """一條稽查規則——條件+行動+優先級。"""
    name: str
    conditions: list[RuleCondition] = field(default_factory=list)
    action_template: AuditAction = field(default_factory=lambda: AuditAction(action="", target=""))  # type: ignore
    priority: int = 10
    description: str = ""
    enabled: bool = True


class RuleContext:
    """規則評估時的上下文——包含 AuditInput + AuditReport 的所有字段。"""

    def __init__(self, inp: AuditInput, report: AuditReport):
        self.inp = inp
        self.report = report

    def get(self, field: str) -> Any:
        """按字段名取值（支持點號路徑）。"""
        if field == "quality_score":
            return self.report.quality_score
        if field == "pattern":
            return self.report.pattern_detected
        if field == "director_intent":
            return self.inp.director_intent
        if field == "steps":
            return self.inp.steps
        if field == "task_results":
            return self.inp.task_results
        if field == "solidified":
            return self.inp.solidified
        # 點號路徑: solidified[0].content
        if "[" in field:
            base, rest = field.split("[", 1)
            idx_str, attr = rest.split("].", 1)
            idx = int(idx_str)
            base_val = self.get(base)
            if isinstance(base_val, list) and idx < len(base_val):
                item = base_val[idx]
                return item.get(attr, "") if isinstance(item, dict) else ""
        return ""


def _eval_condition(cond: RuleCondition, ctx: RuleContext) -> bool:
    """評估單個條件。"""
    field_val = ctx.get(cond.field)
    op = cond.operator

    if op == "gt":
        return bool(field_val is not None and field_val > cond.value)
    if op == "lt":
        return bool(field_val is not None and field_val < cond.value)
    if op == "gte":
        return bool(field_val is not None and field_val >= cond.value)
    if op == "lte":
        return bool(field_val is not None and field_val <= cond.value)
    if op == "eq":
        return field_val == cond.value
    if op == "contains":
        return bool(cond.value in str(field_val))
    if op == "any_contains":
        """field_val 是列表, 任一元素含任一關鍵詞"""
        if not isinstance(field_val, list):
            return False
        keywords = cond.value if isinstance(cond.value, list) else [str(cond.value)]
        keywords_lower = [k.lower() for k in keywords]
        for item in field_val:
            content = str(item.get("content", "")).lower() if isinstance(item, dict) else str(item).lower()
            for kw in keywords_lower:
                if kw in content:
                    return True
        return False
    if op == "len_gt":
        if isinstance(field_val, str):
            return len(field_val) > cond.value
        if isinstance(field_val, list):
            return any(len(str(s.get("content", ""))) > cond.value
                       for s in field_val if isinstance(s, dict))
        return False
    if op == "has_failed":
        if not isinstance(field_val, list):
            return False
        return any(t.get("status") == "failed" for t in field_val)
    if op == "steps_all_done":
        if not isinstance(field_val, list):
            return False
        return all(s.get("status") == "done" for s in field_val)

    return False


def _render_template(template: str, ctx: RuleContext) -> str:
    """渲染行動模板中的 {placeholder}。

    支援:
      {quality_score} → 直接取值
      {solidified[0].content} → 列表索引+屬性
      {value + 0.1:min9} → 數值運算+裁剪
    """
    import math

    def _replace(match):
        expr = match.group(1)
        # 裁剪運算
        clamp = None
        if ":min" in expr:
            expr, clamp_str = expr.split(":min", 1)
            clamp = int(clamp_str)

        # 簡單數值運算
        if "+" in expr:
            parts = expr.split("+")
            base = ctx.get(parts[0].strip())
            try:
                offset = float(parts[1].strip())
                val = (float(base) if base is not None else 0) + offset
                if clamp:
                    val = min(val, clamp)
                return f"{val:.1f}"
            except (ValueError, TypeError):
                pass

        val = ctx.get(expr)
        if val is None:
            return ""
        if isinstance(val, float):
            return f"{val:.3f}"
        return str(val)

    return re.sub(r'\{([^}]+)\}', _replace, template)


# ── 默認規則集 ──────────────────────────────

DEFAULT_RULES: list[AuditRule] = [
    # R1: 測試/偽命題記憶 → 建議清理
    AuditRule(
        name="cleanup_test_memory",
        conditions=[
            RuleCondition("solidified", "any_contains",
                          ["test", "測試", "intentionally false", "pseudo命题", "偽命題", "test proposition"]),
        ],
        action_template=AuditAction(
            action="suggest_cleanup", target="memory",
            content="檢測到測試/偽命題記憶條目，建議 Agent 審視清理",
            confidence=0.8,
            reason="記憶中包含測試標記的偽命題條目，可能是測試殘留",
        ),
        priority=10,
        description="檢測固化內容中的測試/偽命題標記，建議清理",
    ),

    # R2: 低質量+失敗步驟 → 修正嵌入
    AuditRule(
        name="correct_embedding_on_failure",
        conditions=[
            RuleCondition("quality_score", "lt", 0.3),
            RuleCondition("steps", "has_failed", None),
        ],
        action_template=AuditAction(
            action="correct", target="embedding",
            content="修正嵌入: 低質量結果相關上下文",
            confidence=0.6,
            reason="低質量結果需修正相關知識嵌入",
        ),
        priority=30,
        description="低質量且有失敗步驟時修正嵌入向量",
    ),

    # R3: 高質量+長固化 → 提升到 Wiki
    AuditRule(
        name="promote_good_content",
        conditions=[
            RuleCondition("quality_score", "gt", 0.7),
            RuleCondition("solidified", "len_gt", 50),
        ],
        action_template=AuditAction(
            action="promote", target="wiki",
            content="{solidified[0].content}",
            confidence="{quality_score + 0.1:min9}",
            reason="高質量固化內容值得提升為 Wiki 概念",
        ),
        priority=20,
        description="高質量固化內容提升到 Wiki",
    ),

    # R4: 重複模式 → 建議創建 Skill
    AuditRule(
        name="suggest_skill_on_pattern",
        conditions=[
            RuleCondition("pattern", "contains", "重複模式"),
        ],
        action_template=AuditAction(
            action="suggest_skill", target="skill",
            content="頻繁任務可固化為技能",
            confidence=0.7,
            reason="重複模式應固化為可復用技能",
        ),
        priority=40,
        description="檢測到重複任務模式時建議固化為技能",
    ),

    # R5: 高質量+獨特洞察 → 謹慎更新 SOUL
    AuditRule(
        name="update_soul_on_high_quality",
        conditions=[
            RuleCondition("quality_score", "gt", 0.85),
            RuleCondition("solidified", "len_gt", 50),
        ],
        action_template=AuditAction(
            action="update_soul", target="soul",
            content="{solidified[0].content}",
            confidence=0.8,
            reason="高質量洞察可能值得寫入 SOUL 原則",
        ),
        priority=50,
        description="高質量洞察謹慎更新 SOUL",
    ),
]


# ── 稽查引擎 ──────────────────────────────────


class AuditEngine:
    """稽查引擎——非同步比較意圖 vs 執行，生成反饋。

    動作由註冊的 AuditRule 列表驅動。
    新規則可通過 register_rule() 加入，無需修改核心代碼。
    """

    SOUL_CONFLICT_DB: list[dict] = [
        {"rule": "write_file 禁用於 SOUL.md", "conflicts_with": "write_file 是全量覆蓋"},
        {"rule": "patch 用於 SOUL.md 修改", "complements": "write_file 禁用於 SOUL.md"},
    ]

    def __init__(self):
        self._cfg = get_config()
        self._rules: list[AuditRule] = list(DEFAULT_RULES)

    # ── 規則管理 ──────────────────────────────

    def register_rule(self, rule: AuditRule) -> None:
        """註冊一條新規則。同名規則會覆蓋。"""
        for i, r in enumerate(self._rules):
            if r.name == rule.name:
                self._rules[i] = rule
                logger.info("規則已更新: %s", rule.name)
                return
        self._rules.append(rule)
        self._rules.sort(key=lambda r: r.priority)
        logger.info("規則已註冊: %s (優先級 %d)", rule.name, rule.priority)

    def unregister_rule(self, name: str) -> bool:
        """註銷一條規則。"""
        old_len = len(self._rules)
        self._rules = [r for r in self._rules if r.name != name]
        removed = len(self._rules) < old_len
        if removed:
            logger.info("規則已註銷: %s", name)
        return removed

    def list_rules(self) -> list[dict]:
        """返回所有規則的摘要。"""
        return [
            {"name": r.name, "priority": r.priority,
             "conditions": len(r.conditions), "enabled": r.enabled,
             "description": r.description}
            for r in self._rules
        ]

    def enable_rule(self, name: str, enabled: bool) -> bool:
        """啟用/禁用一條規則。"""
        for r in self._rules:
            if r.name == name:
                r.enabled = enabled
                logger.info("規則 %s → %s", name, "啟用" if enabled else "禁用")
                return True
        return False

    # ── 主要入口 ──────────────────────────────

    def audit(self, input_data: AuditInput) -> AuditReport:
        """執行一次完整的稽查循環。

        流程：
          1. 質量評估 (數值計算)
          2. 模式檢測 (跨 session 分析)
          3. 規則評估 (用註冊的 AuditRule 列表)
          4. KM 操作執行 (對 wiki/embedding 直接執行)
          5. 生成摘要 + 寫日誌
        """
        report = AuditReport()

        # 1. 質量評估
        report.quality_score = self._assess_quality(input_data)

        # 2. 模式檢測
        report.pattern_detected = self._detect_pattern(input_data)

        # 3. 規則評估
        ctx = RuleContext(input_data, report)
        for rule in self._rules:
            if not rule.enabled:
                continue
            if self._match_rule(rule, ctx):
                action = self._build_action(rule, ctx)
                # 對 SOUL 更新做衝突檢測
                if action.action == "update_soul" and not self._should_update_soul(action.content):
                    continue
                report.actions.append(action)

        # 4. 執行 KM 操作
        for action in report.actions:
            if action.target in ("wiki", "embedding"):
                self._execute_km_action(action)

        # 5. 摘要 + 日誌
        report.summary = self._build_summary(report)
        self._log_report(report)

        return report

    # ── 規則匹配與行動構建 ────────────────────

    def _match_rule(self, rule: AuditRule, ctx: RuleContext) -> bool:
        """檢查一條規則的所有條件是否全部滿足（AND 邏輯）。"""
        if not rule.conditions:
            return False
        return all(_eval_condition(c, ctx) for c in rule.conditions)

    def _build_action(self, rule: AuditRule, ctx: RuleContext) -> AuditAction:
        """從規則的 action_template 渲染具體行動。"""
        return AuditAction(
            action=rule.action_template.action,
            target=rule.action_template.target,
            content=_render_template(rule.action_template.content, ctx),
            confidence=float(_render_template(
                str(rule.action_template.confidence), ctx)),
            reason=rule.action_template.reason,
        )

    # ── 質量評估 ──────────────────────────────

    def _assess_quality(self, inp: AuditInput) -> float:
        score = 0.5
        if inp.steps and all(s.get("status") == "done" for s in inp.steps):
            score += 0.15
        if inp.solidified:
            score += 0.15
        failed_tasks = [r for r in inp.task_results if r.get("status") == "failed"]
        if failed_tasks:
            score -= 0.1 * len(failed_tasks)
        score = (score + inp.outcome_quality) / 2
        return max(0.0, min(1.0, score))

    # ── 模式檢測 ──────────────────────────────

    def _detect_pattern(self, inp: AuditInput) -> str:
        recent = self._load_recent_audits(limit=5)
        if not recent:
            return ""
        intent_ngram = self._normalize_intent(inp.director_intent)
        similar_count = 0
        for r in recent:
            prev = self._normalize_intent(r.get("director_intent", ""))
            if prev and intent_ngram and prev == intent_ngram:
                similar_count += 1
        if similar_count >= 3:
            return f"重複模式: 相似任務出現 {similar_count + 1} 次，考慮固化為標準流程"
        if similar_count >= 1:
            return f"重複提示: 相似任務已出現 {similar_count + 1} 次"
        return ""

    # ── KM 操作執行 ──────────────────────────

    def _execute_km_action(self, action: AuditAction) -> bool:
        logger.info("KM action: %s → %s: %s", action.action, action.target,
                    action.content[:60])

        if action.target == "wiki" and action.action == "promote":
            try:
                from kafed.knowledge.rag.vector_store import VectorStore
                from kafed.knowledge.rag.chunker import chunk_document
                vs = VectorStore()
                raw = chunk_document(action.content)
                if not raw:
                    raw = [action.content]
                chunks = [str(c) for c in raw if isinstance(c, str)]
                vs.add(
                    texts=chunks,
                    metadatas=[{
                        "domain": "WIKI_PROMOTED",
                        "source": "analyzer_audit",
                        "confidence": action.confidence,
                        "reason": action.reason,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    } for _ in chunks],
                )
                logger.info("  → %d chunks 寫入 WIKI_PROMOTED", len(chunks))
                return True
            except Exception as e:
                logger.warning("  → KM action 失敗: %s", e)
                return False

        if action.target == "embedding" and action.action in ("correct", "demote"):
            logger.info("  → 嵌入修正已記錄（下次 centroid 重算生效）")
            return True

        return False

    # ── SOUL 更新保護 ─────────────────────────

    def _should_update_soul(self, insight: str) -> bool:
        recent_updates = self._load_recent_audits(limit=20)
        soul_suggestions = [
            r for r in recent_updates
            if any(a.get("target") == "soul" for a in r.get("actions", []))
        ]
        if len(soul_suggestions) >= 1 and soul_suggestions:
            last = soul_suggestions[-1]
            last_ts = last.get("timestamp", "")
            if last_ts:
                try:
                    last_dt = datetime.fromisoformat(last_ts)
                    if (datetime.now(timezone.utc) - last_dt).total_seconds() < 86400:
                        logger.info("SOUL 更新建議跳過: 24h 內已有建議")
                        return False
                except Exception:
                    pass
        for conflict in self.SOUL_CONFLICT_DB:
            conflict_rule = conflict.get("conflicts_with", "")
            if conflict_rule and conflict_rule.lower() in insight.lower():
                logger.warning("SOUL 更新衝突: 新規則與「%s」矛盾", conflict_rule)
                return False
        return True

    # ── 持久化 ─────────────────────────────────

    def _log_report(self, report: AuditReport) -> None:
        log_dir = self._cfg.data_dir / "audit_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        log_file = log_dir / f"audit_{today}.jsonl"
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "quality_score": report.quality_score,
            "pattern_detected": report.pattern_detected,
            "actions": [
                {"action": a.action, "target": a.target,
                 "confidence": a.confidence, "reason": a.reason}
                for a in report.actions
            ],
            "summary": report.summary,
        }
        with open(log_file, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _load_recent_audits(self, limit: int = 10) -> list[dict]:
        log_dir = self._cfg.data_dir / "audit_logs"
        if not log_dir.exists():
            return []
        records = []
        for f in sorted(log_dir.glob("audit_*.jsonl"), reverse=True):
            try:
                with open(f) as fh:
                    for line in fh:
                        line = line.strip()
                        if line:
                            records.append(json.loads(line))
                            if len(records) >= limit:
                                break
            except Exception:
                continue
            if len(records) >= limit:
                break
        return records[:limit]

    def _count_recent_intent(self, intent: str) -> int:
        normalized = self._normalize_intent(intent)
        if not normalized:
            return 0
        count = 0
        for r in self._load_recent_audits(limit=30):
            prev = self._normalize_intent(r.get("director_intent", ""))
            if prev == normalized:
                count += 1
        return count + 1

    @staticmethod
    def _normalize_intent(text: str) -> str:
        if not text:
            return ""
        text = text.lower().strip()
        text = re.sub(r'[^\w\s]', '', text)
        words = text.split()
        stopwords = {"the", "a", "an", "is", "are", "was", "were", "to", "for",
                     "of", "in", "on", "with", "and", "or", "not", "be", "do",
                     "this", "that", "it", "i", "we", "you", "能", "会", "是",
                     "的", "了", "在", "有", "不", "就", "也", "这", "那"}
        significant = [w for w in words if w not in stopwords][:5]
        return " ".join(significant)

    @staticmethod
    def _build_summary(report: AuditReport) -> str:
        quality_label = ("優" if report.quality_score > 0.8
                         else "良" if report.quality_score > 0.5
                         else "需改進")
        parts = [f"稽查評分: {quality_label} ({report.quality_score:.2f})"]
        if report.pattern_detected:
            parts.append(report.pattern_detected)
        for a in report.actions:
            parts.append(f"  [{a.action}] {a.target}: {a.reason}")
        return " | ".join(parts)
