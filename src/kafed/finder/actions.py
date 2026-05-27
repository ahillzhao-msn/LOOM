"""Finder 層動作註冊——對應 KAFED F 層對外介面函數。"""
from kafed.action_registry import registry, Action


def _match_fn(brief="", domain="", k=5):
    from kafed.finder.router import find_partners
    return find_partners(brief=brief, domain=domain, k=k)


def _scan_fn():
    from kafed.finder.explorer import explore
    return explore()


def _probe_fn():
    from kafed.finder.heartbeat import probe_all
    return probe_all()


def _record_fn(context_vec=None, model=""):
    from kafed.finder.context_space import ContextSpace
    cs = ContextSpace()
    return cs.record(context_vec=context_vec, model=model)


registry.register(Action(id="finder_search",   code="F",
    labels={"zh": "搜", "en": "Search"},
    description="搜索模型"))
registry.register(Action(id="finder_match",    code="F",
    labels={"zh": "配", "en": "Match"},
    description="匹配候選", fn=_match_fn))
registry.register(Action(id="finder_merge",    code="F",
    labels={"zh": "併", "en": "Merge"},
    description="合併結果"))
registry.register(Action(id="finder_scan",     code="F",
    labels={"zh": "掃", "en": "Scan"},
    description="掃描全量", fn=_scan_fn))
registry.register(Action(id="finder_probe",    code="F",
    labels={"zh": "探", "en": "Probe"},
    description="心跳探測", fn=_probe_fn))
registry.register(Action(id="finder_buffer",   code="F",
    labels={"zh": "蓄", "en": "Buffer"},
    description="上下文緩衝", fn=_record_fn))
registry.register(Action(id="finder_route",    code="F",
    labels={"zh": "路由", "en": "Route"},
    description="路由策略"))