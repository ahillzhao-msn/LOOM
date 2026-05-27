"""KAFED — Knowledge Agent Framework for Embedded Data.

五層智能飛輪：Knowledge → Analysis → Finder → Executor → Director
知識管理、自主分析、三維路由、DAG執行、戰略規劃。

雙模式：本地導入（零進程）或 HTTP 服務（可選 FastAPI）。
"""

__version__ = "2.2.2"

# ── Action 自動註冊 ──
from kafed import action_registry  # noqa: F401
import kafed.director.actions     # noqa: F401
import kafed.knowledge.actions    # noqa: F401
import kafed.finder.actions       # noqa: F401
import kafed.executor.actions     # noqa: F401
import kafed.analyzer.actions     # noqa: F401
