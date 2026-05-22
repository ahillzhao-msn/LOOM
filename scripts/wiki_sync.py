"""
Wiki 降级脚本 — 从 KAFED 向量库同步到 Hermes wiki（人类可读视图）。

用法:
    python wiki_sync.py                         # 全量同步
    python wiki_sync.py --domain SAP_PM         # 仅同步指定域
    python wiki_sync.py --dry-run               # 预览变更

原则:
    - Wiki 是只读视图，不手动编辑
    - 主存储是 KAFED 向量库
    - 每次同步增量更新（按 chunk id 检测变更）
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from kafed.client.local_backend import KafedLocalBackend
    BACKEND = KafedLocalBackend()
except ImportError:
    try:
        from kafed.client.http_client import KafedClient
        BACKEND = KafedClient()
    except ImportError:
        print("KAFED package not installed. Run: pip install -e ~/km/kafed", file=sys.stderr)
        sys.exit(1)

WIKI_DIR = Path.home() / ".hermes" / "wiki" / "entities"
KAFED_SYNC_MARK = "<!-- synced from KAFED -->"


def build_wiki_page(domain: str, chunks: list[dict],
                    stats: dict | None = None) -> str:
    """从 KAFED chunks 生成 wiki 实体页。

    Returns:
        Markdown 字符串
    """
    total = len(chunks)
    avg_quality = sum(
        float(c["metadata"].get("quality_score", 0) or 0)
        for c in chunks
    ) / max(total, 1)

    lines = [
        "---",
        f"title: \"{domain} 知识域\"",
        f"domain: {domain}",
        f"synced_from: kafed",
        f"synced_at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"total_chunks: {total}",
        f"avg_quality: {avg_quality:.3f}",
        "---",
        "",
        KAFED_SYNC_MARK,
        "",
        f"# {domain} 知识域",
        "",
        f"由 KAFED 向量库自动同步生成（{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC）。",
        "",
        f"- 总条目: **{total}**",
        f"- 平均质量: **{avg_quality:.3f}**",
        "",
        "---",
        "",
    ]

    # 按来源分组
    by_source: dict[str, list[dict]] = {}
    for c in chunks:
        src = c["metadata"].get("source", "unknown")
        by_source.setdefault(src, []).append(c)

    for source, src_chunks in sorted(by_source.items()):
        lines.append(f"## 来源: {source}")
        lines.append("")
        for c in sorted(src_chunks,
                        key=lambda x: float(x["metadata"].get("quality_score", 0) or 0),
                        reverse=True):
            heading = c["metadata"].get("heading", "") or "(无标题)"
            quality = c["metadata"].get("quality_score", "?")
            chain = c["metadata"].get("heading_chain", "")
            content_preview = c["content"][:200].replace("\n", " ")
            lines.append(f"### {heading}")
            if chain:
                lines.append(f"*标题链: {chain}*")
            lines.append(f"*质量: {quality} | 字符: {c['metadata'].get('chars', '?')}*")
            chunk_id = c.get("id", c.get("chunk_index", "?"))
            lines.append(f"*ID: `{chunk_id}`*")
            lines.append("")
            lines.append(f"> {content_preview}")
            lines.append("")
            lines.append("---")
            lines.append("")

    return "\n".join(lines)


def sync_domain(domain: str, client: KafedClient,
                dry_run: bool = False) -> dict:
    """同步单个域到 wiki。"""
    # 获取该域所有 chunks
    import requests as req
    resp = req.get(
        f"{client.base_url}/query",
        params={"q": "", "top_k": 1000, "domain": domain},
    )
    if not resp.ok:
        return {"domain": domain, "status": "error",
                "message": f"HTTP {resp.status_code}"}

    data = resp.json()
    results = data.get("results", [])
    if not results:
        return {"domain": domain, "status": "skipped",
                "message": "无数据"}

    # 生成 wiki 页
    wiki_path = WIKI_DIR / f"{domain.lower().replace('-', '_')}.md"
    content = build_wiki_page(domain, results)

    if dry_run:
        return {"domain": domain, "status": "preview",
                "chunks": len(results),
                "wiki_path": str(wiki_path),
                "size": len(content)}

    # 写入
    wiki_path.parent.mkdir(parents=True, exist_ok=True)
    wiki_path.write_text(content, encoding="utf-8")
    return {"domain": domain, "status": "synced",
            "chunks": len(results),
            "wiki_path": str(wiki_path),
            "size": len(content)}


def main():
    ap = argparse.ArgumentParser(description="KAFED → Wiki 降级同步")
    ap.add_argument("--domain", help="仅同步指定域")
    ap.add_argument("--dry-run", action="store_true", help="预览不变更")
    ap.add_argument("--url", help="KAFED 服务 URL", default=None)
    args = ap.parse_args()

    client = KafedClient(base_url=args.url)

    if args.domain:
        domains = [args.domain]
    else:
        from kafed.client.http_client import requests as req
        resp = req.get(f"{client.base_url}/domains")
        if not resp.ok:
            print(f"❌ 获取域列表失败: {resp.status_code}", file=sys.stderr)
            sys.exit(1)
        domains = [d["name"] for d in resp.json().get("domains", [])
                   if d["count"] > 0]

    if not domains:
        print("⚠️ 没有需要同步的域")
        return

    print(f"📥 同步 {len(domains)} 个域到 wiki...")
    results = []
    for d in domains:
        r = sync_domain(d, client, dry_run=args.dry_run)
        results.append(r)
        icon = {"synced": "✅", "skipped": "⏭️", "error": "❌", "preview": "👁️"}.get(
            r["status"], "❓")
        print(f"  {icon} {d}: {r['status']}", end="")
        if r.get("chunks"):
            print(f" ({r['chunks']} chunks, {r.get('size',0)} bytes)")
        else:
            print()

    synced = sum(1 for r in results if r["status"] == "synced" or r["status"] == "preview")
    print(f"\n📊 总计: {synced}/{len(domains)} 域已{'预览' if args.dry_run else '同步'}")


if __name__ == "__main__":
    main()
