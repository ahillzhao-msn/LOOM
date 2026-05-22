"""
KAFED Python SDK — Hermes knowledge skill 的客户端层。

同步 HTTP 客户端，零依赖（仅 stdlib + requests）。
支持 ingest/query/feedback/stats 全接口。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore


@dataclass
class KafedResult:
    """KAFED API 返回的统一包装。"""
    success: bool
    data: dict = field(default_factory=dict)
    error: str | None = None


TEXT_EXTENSIONS = {".md", ".markdown", ".txt"}


def _is_text_path(path: Path) -> bool:
    return path.suffix.lower() in TEXT_EXTENSIONS


class KafedClient:
    """KAFED RAG 服务客户端。

    核心 API (/ingest) 只接受 Markdown/TXT 文件。
    PDF 等其他格式请使用 ingest_convert() (需要系统安装 doc2md)。
    """

    def __init__(self, base_url: str | None = None, timeout: int = 30):
        self.base_url = (base_url or
                         os.getenv("KAFED_API_URL", "http://localhost:8765")).rstrip("/")
        self.timeout = timeout

        if requests is None:
            raise ImportError(
                "KAFED 客户端需要 `requests` 库。"
                " pip install requests"
            )

    # ── 文档摄入（核心 API：仅 MD/TXT） ─────────────────

    def ingest(self, file_path: str | Path, domain: str = "GENERAL") -> KafedResult:
        """上传 Markdown/TXT 文件到 KAFED 向量库。

        Args:
            file_path: .md / .markdown / .txt 文件路径
            domain: 知识域（如 "SAP_PM", "GENERAL"）
        """
        path = Path(file_path)
        if not path.exists():
            return KafedResult(False, error=f"文件不存在: {path}")

        suffix = path.suffix.lower()
        if suffix not in TEXT_EXTENSIONS:
            return KafedResult(False,
                error=f"核心 API 只接受 MD/TXT（收到 {suffix}）。"
                      f"PDF 等格式请用 ingest_convert() 方法。")

        with open(path, "rb") as f:
            resp = requests.post(
                urljoin(self.base_url, "/ingest"),
                files={"file": (path.name, f, "text/markdown")},
                data={"domain": domain},
                timeout=self.timeout,
            )
        return self._handle(resp)

    def ingest_text(self, text: str, filename: str = "inline.md",
                    domain: str = "GENERAL") -> KafedResult:
        """直接摄入 Markdown 文本（无需本地文件）。"""
        resp = requests.post(
            urljoin(self.base_url, "/ingest"),
            files={"file": (filename, text.encode("utf-8"), "text/markdown")},
            data={"domain": domain},
            timeout=self.timeout,
        )
        return self._handle(resp)

    # ── 文档摄入（便利入口：调用外部 doc2md） ──────────

    def ingest_convert(self, file_path: str | Path,
                       domain: str = "GENERAL") -> KafedResult:
        """上传任意格式文档 → 系统 doc2md 转换 → 存入向量库。

        需要系统安装 doc2md CLI。
        """
        path = Path(file_path)
        if not path.exists():
            return KafedResult(False, error=f"文件不存在: {path}")

        with open(path, "rb") as f:
            resp = requests.post(
                urljoin(self.base_url, "/ingest/convert"),
                files={"file": (path.name, f, "application/octet-stream")},
                data={"domain": domain},
                timeout=self.timeout * 2,  # 转换可能需要更长时间
            )
        return self._handle(resp)

    # ── 检索 ──────────────────────────────────────────────

    def query(self, question: str, top_k: int = 5,
              domain: str | None = None) -> KafedResult:
        """语义搜索知识库。"""
        params = {"q": question, "top_k": top_k}
        if domain:
            params["domain"] = domain
        resp = requests.get(
            urljoin(self.base_url, "/query"),
            params=params,
            timeout=self.timeout,
        )
        return self._handle(resp)

    # ── 反馈 ──────────────────────────────────────────────

    def feedback(self, query_id: str, doc_id: str, score: int = 5,
                 user_id: str = "anonymous") -> KafedResult:
        """对检索结果评分。score: 1-5。"""
        resp = requests.post(
            urljoin(self.base_url, "/feedback"),
            json={
                "query_id": query_id,
                "doc_id": doc_id,
                "score": score,
                "user_id": user_id,
            },
            timeout=self.timeout,
        )
        return self._handle(resp)

    # ── 统计 ──────────────────────────────────────────────

    def stats(self) -> KafedResult:
        """服务统计信息。"""
        resp = requests.get(
            urljoin(self.base_url, "/stats"),
            timeout=self.timeout,
        )
        return self._handle(resp)

    def domains(self) -> KafedResult:
        """所有知识域列表。"""
        resp = requests.get(
            urljoin(self.base_url, "/domains"),
            timeout=self.timeout,
        )
        return self._handle(resp)

    # ── 内部 ──────────────────────────────────────────────

    @staticmethod
    def _handle(resp: requests.Response) -> KafedResult:
        try:
            data = resp.json()
        except json.JSONDecodeError:
            return KafedResult(
                resp.ok,
                error=f"HTTP {resp.status_code}: {resp.text[:200]}",
            )
        if resp.ok:
            return KafedResult(True, data=data)
        return KafedResult(False, data=data,
                           error=data.get("detail", str(data)))
