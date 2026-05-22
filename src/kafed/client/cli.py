"""KAFED CLI — `python -m kafed` 或 `kafed`（安裝後）。

用法:
    kafed query <question>          查詢知識庫
    kafed ingest <file.md>          攝入文檔
    kafed stats                     系統統計
    kafed scan [--update-roster]    掃描模型列表
    kafed feedback <query_id> <doc_id> <score>  反饋評分
"""

from __future__ import annotations

import argparse
import json
import sys


def main() -> None:
    parser = argparse.ArgumentParser(prog="kafed", description="KAFED 知識庫工具")
    sub = parser.add_subparsers(dest="command", required=True)

    # query
    q = sub.add_parser("query", help="查詢知識庫")
    q.add_argument("question", help="查詢問題")
    q.add_argument("-d", "--domain", help="領域過濾", default=None)
    q.add_argument("-k", "--top-k", type=int, default=5, help="返回條數")

    # ingest
    i = sub.add_parser("ingest", help="攝入文檔")
    i.add_argument("file", help="文檔路徑 (.md/.txt)")
    i.add_argument("-d", "--domain", help="指定領域（默認自動分類）", default=None)

    # stats
    sub.add_parser("stats", help="系統統計")

    # scan
    s = sub.add_parser("scan", help="掃描模型列表")
    s.add_argument("--update-roster", action="store_true", help="更新 roster + 向量空間")

    # feedback
    f = sub.add_parser("feedback", help="反饋評分")
    f.add_argument("query_id", help="查詢 ID")
    f.add_argument("doc_id", help="文檔 ID")
    f.add_argument("score", type=int, help="評分 (1-5)")

    args = parser.parse_args()
    _execute(args)


def _execute(args: argparse.Namespace) -> None:
    try:
        from kafed.client.local_backend import KafedLocalBackend
        backend = KafedLocalBackend()
    except ImportError as e:
        print(f"KAFED 導入失敗: {e}", file=sys.stderr)
        sys.exit(1)

    if args.command == "query":
        result = backend.query(args.question, top_k=args.top_k, domain=args.domain)
        print(f"查詢: {result['question']}")
        print(f"搜索到 {result['total_found']} 條結果")
        for r in result.get("results", []):
            score = r.get("score", 0)
            content = r.get("content", "")[:120]
            print(f"  [{score:.2f}] {content}")
        if result.get("domain_context"):
            dc = result["domain_context"]
            print(f"域上下文: {dc.get('domain')} ({dc.get('total_entries', 0)} 條)")

    elif args.command == "ingest":
        result = backend.ingest(args.file, domain=args.domain)
        status = result.get("status", "error")
        chunks = result.get("chunks", 0)
        domain = result.get("domain", "?")
        print(f"攝入狀態: {status}")
        print(f"  分塊: {chunks}")
        print(f"  領域: {domain}")
        if result.get("events"):
            for ev in result["events"]:
                print(f"  事件: {ev.get('event')} → {ev.get('action_hint')}")

    elif args.command == "stats":
        stats = backend.stats()
        print(f"KAFED 統計")
        print(f"  總 chunks: {stats.get('total_chunks', 0)}")
        print(f"  域數: {len(stats.get('domains', []))}")
        for d in stats.get("domains", [])[:15]:
            print(f"    · {d['name']:20s} {d['count']} chunks")
        if len(stats.get("domains", [])) > 15:
            print(f"    ... and {len(stats['domains']) - 15} more")
        print(f"  反饋總數: {stats.get('total_feedback', 0)}")
        print(f"  centroids: {stats.get('centroids_count', 0)}")

    elif args.command == "scan":
        from kafed.finder.explorer import scan
        workers = scan(update_roster=args.update_roster)
        print(f"Found {len(workers)} workers")

    elif args.command == "feedback":
        from kafed.client.local_backend import KafedLocalBackend
        backend = KafedLocalBackend()
        result = backend.feedback(args.query_id, args.doc_id, score=args.score)
        print(f"反饋已記錄: {result}")


if __name__ == "__main__":
    main()
