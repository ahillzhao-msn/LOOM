"""Analyzer 層動作註冊——對應 KAFED A 層對外介面函數。"""
from kafed.action_registry import registry, Action


def _pulse_fn():
    # PulseScheduler tick is the heartbeat of the system
    from kafed.analyzer.pulse import PulseScheduler
    s = PulseScheduler()
    return s.tick()


def _audit_fn(input_data=None):
    from kafed.analyzer.audit import AuditEngine
    engine = AuditEngine()
    return engine.run(input_data=input_data)


def _kb_audit_fn():
    from kafed.analyzer.kb_audit import KbAuditor
    auditor = KbAuditor()
    return auditor.run()


def _quality_fn(text=""):
    from kafed.knowledge.quality import QualityFilter
    qf = QualityFilter()
    return qf.check(text=text)


# ── Analyzer 核心 ──
registry.register(Action(id="analyzer_pulse",    code="A",
    labels={"zh": "脈", "en": "Pulse"},
    description="脈動檢查", fn=_pulse_fn))

registry.register(Action(id="analyzer_audit",    code="A",
    labels={"zh": "審", "en": "Audit"},
    description="會話審計", fn=_audit_fn))

registry.register(Action(id="analyzer_kb_audit", code="A",
    labels={"zh": "勘", "en": "KB_Audit"},
    description="知識庫勘驗", fn=_kb_audit_fn))

registry.register(Action(id="analyzer_quality",  code="A",
    labels={"zh": "質", "en": "Quality"},
    description="質量檢查", fn=_quality_fn))

# ── Backlog 佇列（Analyzer 管理分析任務排程）──
def _backlog_push_fn(title="", value=0.7, description=""):
    from kafed.backlog import push
    return push(title=title, value=value, description=description)

def _backlog_check_fn():
    from kafed.backlog import check
    return check()

def _backlog_pop_fn():
    from kafed.backlog import pop
    return pop()

registry.register(Action(id="backlog_accumulate", code="A",
    labels={"zh": "積", "en": "Accum"},
    description="積累待辦"))
registry.register(Action(id="backlog_push",      code="A",
    labels={"zh": "推", "en": "Push"},
    description="推入待辦", fn=_backlog_push_fn))
registry.register(Action(id="backlog_check",     code="A",
    labels={"zh": "檢", "en": "Check"},
    description="檢查待辦", fn=_backlog_check_fn))
registry.register(Action(id="backlog_pop",       code="A",
    labels={"zh": "取", "en": "Pop"},
    description="取出待辦", fn=_backlog_pop_fn))