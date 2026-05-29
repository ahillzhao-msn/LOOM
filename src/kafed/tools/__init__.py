"""KAFED Tools — Hermes 工具層。

所有暴露給 Hermes Agent 的工具函數。
Symlink: ~/.hermes/hermes-agent/tools/kafed_tool.py → 此檔案
"""

from kafed.tools.hermes_tools import (
    kafed_recommend,
    kafed_find_partners,
    kafed_solidify,
    kafed_query,
    kafed_ingest,
    kafed_status,
    kafed_classify,
)

__all__ = [
    "kafed_recommend",
    "kafed_find_partners",
    "kafed_solidify",
    "kafed_query",
    "kafed_ingest",
    "kafed_status",
    "kafed_classify",
]
