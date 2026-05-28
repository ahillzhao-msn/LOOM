"""KAFED CLI — `python -m kafed`.

用法:
    python -m kafed query <question>          查詢知識庫
    python -m kafed ingest <file.md>          攝入文檔
    python -m kafed stats                     系統統計
    python -m kafed kpak pack <domain>        導出知識包
    python -m kafed kpak unpack <file.kpak>   導入知識包
    python -m kafed kpak list                 列出知識包
"""

from __future__ import annotations

import argparse
import json
import sys


def cmd_query(args):
    from kafed.knowledge.rag.rag_engine import RAGEngine
    engine = RAGEngine()
    results = engine.query(args.question, top_k=args.top_k, domain=args.domain, soft=True)
    for i, r in enumerate(results):
        print(f"[{i+1}] [{r.get('domain','?')}] score={r.get('score',0):.3f}")
        print(f"    {r.get('content','')[:200]}")
        print()


def cmd_ingest(args):
    from kafed.knowledge.ingest import batch_ingest_files
    result = batch_ingest_files([args.file], domain=args.domain or "GENERAL")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_stats(args):
    from kafed.knowledge.rag.vector_store import VectorStore
    from kafed.config import get_config
    cfg = get_config()
    vs = VectorStore()
    print(f"ChromaDB: {cfg.chroma_path}")
    print(f"Chunks:   {vs._collection.count()}")
    print(f"Config:   {cfg.data_dir}")


def cmd_kpak(args):
    if args.kpak_action == "pack":
        from kafed.kpak.pack import pack_domain
        pack_domain(args.domain, args.output)
    elif args.kpak_action == "unpack":
        from kafed.kpak.unpack import unpack_file
        unpack_file(args.file)
    elif args.kpak_action == "list":
        from pathlib import Path
        from kafed.config import get_config
        cfg = get_config()
        kpak_dir = Path(cfg.data_dir) / "kpak"
        files = sorted(kpak_dir.glob("*.kpak")) if kpak_dir.exists() else []
        for f in files:
            print(f"  {f.name}  ({f.stat().st_size:,} bytes)")


def main():
    parser = argparse.ArgumentParser(prog="kafed", description="KAFED 知識引擎")
    sub = parser.add_subparsers(dest="command")

    # query
    q = sub.add_parser("query", help="查詢知識庫")
    q.add_argument("question")
    q.add_argument("-d", "--domain", default=None)
    q.add_argument("-k", "--top-k", type=int, default=5)

    # ingest
    i = sub.add_parser("ingest", help="攝入文檔")
    i.add_argument("file")
    i.add_argument("-d", "--domain", default=None)

    # stats
    sub.add_parser("stats", help="系統統計")

    # kpak subcommands
    kp = sub.add_parser("kpak", help="知識包操作")
    kp_sub = kp.add_subparsers(dest="kpak_action")
    kp_pack = kp_sub.add_parser("pack", help="導出領域")
    kp_pack.add_argument("domain")
    kp_pack.add_argument("-o", "--output", default=None)
    kp_unpack = kp_sub.add_parser("unpack", help="導入知識包")
    kp_unpack.add_argument("file")
    kp_sub.add_parser("list", help="列出知識包")

    args = parser.parse_args()

    if args.command == "query":
        cmd_query(args)
    elif args.command == "ingest":
        cmd_ingest(args)
    elif args.command == "stats":
        cmd_stats(args)
    elif args.command == "kpak":
        cmd_kpak(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
