"""
KAFED CLI — 命令行工具。

用法:
    kafed ingest <file> --domain <domain>
    kafed query <question> [--top-k 5] [--domain <domain>]
    kafed feedback <query_id> <doc_id> --score <1-5>
    kafed stats
    kafed domains
    kafed start                    # 启动本地 RAG 服务
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from kafed.client.http_client import KafedClient


def main():
    parser = argparse.ArgumentParser(
        prog="kafed",
        description="KAFED — Knowledge Agent Framework for Embedded Data",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ingest
    p_ingest = sub.add_parser("ingest", help="摄入 Markdown/TXT 文档")
    p_ingest.add_argument("file", type=str, help="Markdown 或 TXT 文件路径")
    p_ingest.add_argument("--domain", default="GENERAL", help="知识域")
    p_ingest.add_argument("--url", default=None, help="KAFED 服务 URL")

    # ingest-convert
    p_cvt = sub.add_parser("ingest-convert", help="摄入任意文档（调用外部 doc2md 转换）")
    p_cvt.add_argument("file", type=str, help="任意格式文件（PDF/DOCX/图片等）")
    p_cvt.add_argument("--domain", default="GENERAL", help="知识域")
    p_cvt.add_argument("--url", default=None, help="KAFED 服务 URL")

    # query
    p_query = sub.add_parser("query", help="语义搜索")
    p_query.add_argument("question", type=str, help="搜索问题")
    p_query.add_argument("--top-k", type=int, default=5, help="返回条数")
    p_query.add_argument("--domain", default=None, help="限定域")
    p_query.add_argument("--url", default=None, help="KAFED 服务 URL")

    # feedback
    p_fb = sub.add_parser("feedback", help="提交评分")
    p_fb.add_argument("query_id", type=str, help="查询 ID")
    p_fb.add_argument("doc_id", type=str, help="文档片段 ID")
    p_fb.add_argument("--score", type=int, default=5, help="评分 1-5")
    p_fb.add_argument("--url", default=None, help="KAFED 服务 URL")

    # stats
    sub.add_parser("stats", help="服务统计")

    # domains
    sub.add_parser("domains", help="列出知识域")

    # start
    p_start = sub.add_parser("start", help="启动本地 RAG 服务")
    p_start.add_argument("--port", type=int, default=8765, help="监听端口")
    p_start.add_argument("--host", type=str, default="0.0.0.0", help="监听地址")

    args = parser.parse_args()
    client = KafedClient(base_url=args.url) if hasattr(args, "url") else KafedClient()

    if args.command == "ingest":
        result = client.ingest(args.file, args.domain)
        if result.success:
            print(f"✅ 摄入完成: {result.data.get('chunks', 0)} 个分块")
            if result.data.get("events"):
                for e in result.data["events"]:
                    print(f"  飞轮事件 {e['event']}: {e['action']}")
        else:
            print(f"❌ {result.error}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "ingest-convert":
        result = client.ingest_convert(args.file, args.domain)
        if result.success:
            print(f"✅ 转换+摄入完成: {result.data.get('chunks', 0)} 个分块")
            if result.data.get("events"):
                for e in result.data["events"]:
                    print(f"  飞轮事件 {e['event']}: {e['action']}")
        else:
            print(f"❌ {result.error}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "query":
        result = client.query(args.question, args.top_k, args.domain)
        if result.success:
            data = result.data
            print(f"\n查询: {data['question']}")
            print(f"查询ID: {data['query_id']}")
            print(f"找到 {data['total_found']} 条结果:\n")
            for i, r in enumerate(data["results"], 1):
                print(f"── [{i}] (score={r['score']:.3f}) ────────────────")
                print(f"  域: {r['metadata'].get('domain', '?')}")
                print(f"  来源: {r['metadata'].get('source', '?')}")
                print(f"  {r['content'][:200]}...")
                print()
        else:
            print(f"❌ {result.error}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "feedback":
        result = client.feedback(args.query_id, args.doc_id, args.score)
        if result.success:
            print(f"✅ 反馈已记录 (query_id={args.query_id})")
            if result.data.get("events"):
                for e in result.data["events"]:
                    print(f"  飞轮事件 {e['event']}: {e['action']}")
        else:
            print(f"❌ {result.error}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "stats":
        result = client.stats()
        if result.success:
            d = result.data
            print(f"总条目: {d['total_chunks']}")
            print(f"总反馈: {d['total_feedback']}")
            print(f"Centroids: {d['centroids_count']}")
            print("\n域分布:")
            for dom in d.get("domains", []):
                print(f"  {dom['name']}: {dom['count']} 条")
        else:
            print(f"❌ {result.error}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "domains":
        result = client.domains()
        if result.success:
            print("知识域:")
            for d in result.data.get("domains", []):
                print(f"  {d['name']}: {d['count']} 条目")
        else:
            print(f"❌ {result.error}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "start":
        # 启动 FastAPI 服务
        import uvicorn  # noqa
        print(f"🔄 启动 KAFED RAG 服务于 {args.host}:{args.port} ...")
        os.environ.setdefault("KAFED_HOST", args.host)
        os.environ.setdefault("KAFED_PORT", str(args.port))
        from kafed.server.main import main as server_main
        server_main()


if __name__ == "__main__":
    main()
