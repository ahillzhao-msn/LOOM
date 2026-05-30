"""Loom (织机) — Conversation-level session management for LOOM.

將分散的對話輪次（threads）編織成連貫的知識結構（fabric），
為飛輪提供完整的決策軌跡。

三層資料結構：
  Conversation → Session (1:n) → Turn (1:n)
"""

from .models import TurnRecord, SessionRecord, ConversationRecord
from .factory import TurnFactory, SessionFactory, ConversationFactory
from .client import manager, get_manager
from .shuttle import Shuttle

__all__ = [
    "TurnRecord", "SessionRecord", "ConversationRecord",
    "TurnFactory", "SessionFactory", "ConversationFactory",
    "manager", "get_manager",
    "Shuttle",
]
