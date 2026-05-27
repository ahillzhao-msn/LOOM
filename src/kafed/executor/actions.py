"""Executor 層動作註冊——對應 KAFED E 層對外介面函數。"""
from kafed.action_registry import registry, Action


def _dispatch_fn(task_id="", model_name=""):
    from kafed.executor.dispatcher import Dispatcher
    d = Dispatcher()
    return d.dispatch(task_id=task_id, model_name=model_name)


def _dag_fn(tasks=None):
    from kafed.executor.engine import ExecutorEngine
    engine = ExecutorEngine()
    return engine.execute_dag(tasks=tasks or [])


registry.register(Action(id="executor_dispatch", code="E",
    labels={"zh": "遣", "en": "Dispatch"},
    description="任務調度派遣", fn=_dispatch_fn))

registry.register(Action(id="executor_dag",      code="E",
    labels={"zh": "遣", "en": "[DAG]"},
    description="DAG 多任務編排", fn=_dag_fn))