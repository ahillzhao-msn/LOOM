"""KAFED 全局日誌模塊。

統一日誌格式、雙通道（文件+控制台）、可配置日誌級別。
所有 KAFED 模塊通過 from kafed.log import logger 使用。

用法：
    from kafed.log import logger
    logger.info("模型加載完成", extra={"model": "bge-small", "dim": 384})
    logger.warning("嵌入維度不匹配")
    logger.error("Chroma 連接失敗", exc_info=True)

雙通道：
    - 控制台：WARNING+，彩色時間戳（生產環境可調）
    - 日誌文件：INFO+，JSON 結構化（data_dir/logs/kafed.log）

所有路徑通過 config.py 的 data_dir 派生。
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── 日誌格式常量 ──────────────────────────────

_CONSOLE_FORMAT = "%(asctime)s [%(levelname)-5s] %(name)s | %(message)s"
_CONSOLE_DATE = "%H:%M:%S"
_FILE_FORMAT = "%(asctime)s [%(levelname)-5s] %(name)s | %(message)s"
_FILE_DATE = "%Y-%m-%d %H:%M:%S"

# ── 配置（按優先級） ──────────────────────────

_LOG_LEVEL = os.getenv("KAFED_LOG_LEVEL", "INFO").upper()
_LOG_FILE_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_LOG_FILE_BACKUP_COUNT = 3


def _resolve_data_dir() -> Path:
    """嘗試從 config 獲取 data_dir，失敗則 fallback 到 ~/.kafed/data。"""
    try:
        from kafed.config import get_config
        return get_config().data_dir
    except Exception:
        return Path.home() / ".kafed" / "data"


def _init_logger(name: str = "kafed") -> logging.Logger:
    """初始化 root logger。只執行一次。"""
    root = logging.getLogger(name)
    if root.handlers:
        return root  # 已初始化

    root.setLevel(_LOG_LEVEL)
    root.handlers.clear()

    # 1. 控制台 handler（WARNING+）
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(max(getattr(logging, _LOG_LEVEL), logging.WARNING))
    console.setFormatter(logging.Formatter(_CONSOLE_FORMAT, _CONSOLE_DATE))
    root.addHandler(console)

    # 2. 文件 handler（配置級別）
    data_dir = _resolve_data_dir()
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "kafed.log"

    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=_LOG_FILE_MAX_BYTES,
        backupCount=_LOG_FILE_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(getattr(logging, _LOG_LEVEL))
    file_handler.setFormatter(logging.Formatter(_FILE_FORMAT, _FILE_DATE))
    root.addHandler(file_handler)

    return root


# ── 初始化 ─────────────────────────────────────

logger = _init_logger()


# ── 結構化日誌工具（可選） ────────────────────

def log_json(level: int, message: str, **fields: Any) -> None:
    """寫 JSON 結構化日誌供日誌文件分析。"""
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": logging.getLevelName(level),
        "message": message,
        **fields,
    }
    logger.log(level, json.dumps(record, ensure_ascii=False, default=str))


def log_startup(name: str, version: str) -> None:
    """服務啟動日誌。"""
    logger.info(f"{name} v{version} 啟動", extra={"event": "startup", "version": version})


def log_shutdown(name: str) -> None:
    """服務關閉日誌。"""
    logger.info(f"{name} 關閉", extra={"event": "shutdown"})
