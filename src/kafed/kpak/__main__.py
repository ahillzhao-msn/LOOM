#!/usr/bin/env python3
"""KAFED 知识包 CLI — python -m kafed.kpak <command>

命令:
    pack   <domain>      将指定域打包为 .kpak
    unpack <kpak_path>   导入 .kpak 到向量库
    list                 列出所有可用 .kpak
    info   <kpak_path>   查看 .kpak 包信息
"""

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="KAFED 知识包管理 — 域知识导出/导入/查看",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("command", choices=["pack", "unpack", "list", "info"],
                        help="操作命令")
    parser.add_argument("arg", nargs="?", default=None,
                        help="domain（pack）或 .kpak 路径（unpack/info）")
    parser.add_argument("-o", "--output-dir", default=None,
                        help="pack 输出目录（默认 config.kpak_dir）")
    parser.add_argument("--no-centroid", action="store_true",
                        help="pack 时跳过 centroid 向量")

    args = parser.parse_args()

    # ── 延迟导入，避免 chromadb 在 --help 时加载 ──
    try:
        from kafed.kpak.pack import pack_domain, list_kpak
        from kafed.kpak.unpack import unpack_kpak
    except ImportError as e:
        print(f"错误: 无法加载 kafed.kpak — {e}", file=sys.stderr)
        sys.exit(1)

    if args.command == "pack":
        if not args.arg:
            print("错误: pack 需要 domain 参数（如 SAP_PM）", file=sys.stderr)
            sys.exit(1)
        try:
            path = pack_domain(args.arg, output_dir=args.output_dir,
                               include_centroid=not args.no_centroid)
            print(f"✅ 打包完成: {path}")
            print(f"   域: {args.arg}")
            # 显示包信息
            info = _inspect_kpak(path)
            if info:
                print(f"   条目: {info['entries']}")
                print(f"   嵌入: {info['embedding_model']} ({info['embedding_dim']}d)")
                print(f"   创建: {info['created_at'][:19]}")
        except Exception as e:
            print(f"❌ 打包失败: {e}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "unpack":
        if not args.arg:
            print("错误: unpack 需要 .kpak 路径参数", file=sys.stderr)
            sys.exit(1)
        kpak_path = Path(args.arg)
        if not kpak_path.exists():
            print(f"❌ 文件不存在: {kpak_path}", file=sys.stderr)
            sys.exit(1)
        try:
            result = unpack_kpak(kpak_path)
            print(f"✅ 导入完成")
            print(f"   域: {result['domain']}")
            print(f"   导入: {result['imported']} 条")
            print(f"   centroid 合并: {'是' if result['merged_centroid'] else '否'}")
        except Exception as e:
            print(f"❌ 导入失败: {e}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "list":
        try:
            pkgs = list_kpak(output_dir=args.output_dir)
        except Exception as e:
            pkgs = []
            print(f"⚠ 无法扫描: {e}", file=sys.stderr)

        if not pkgs:
            print("(无可用 .kpak 包)")
            return

        print(f"可用知识包 ({len(pkgs)}):")
        print(f"{'域':<20} {'条目':<8} {'创建时间':<22} {'路径'}")
        print("-" * 80)
        for p in sorted(pkgs, key=lambda x: x.get("created", ""), reverse=True):
            print(f"{p['domain']:<20} {p['entries']:<8} {str(p.get('created', ''))[:19]:<22} {p['path']}")

    elif args.command == "info":
        if not args.arg:
            print("错误: info 需要 .kpak 路径参数", file=sys.stderr)
            sys.exit(1)
        kpak_path = Path(args.arg)
        if not kpak_path.exists():
            print(f"❌ 文件不存在: {kpak_path}", file=sys.stderr)
            sys.exit(1)
        info = _inspect_kpak(kpak_path)
        if info:
            print(f"知识包: {kpak_path.name}")
            print(f"  大小: {kpak_path.stat().st_size / 1024:.1f} KB")
            for k, v in info.items():
                print(f"  {k}: {v}")
        else:
            print(f"❌ 无法读取: {kpak_path}", file=sys.stderr)
            sys.exit(1)


def _inspect_kpak(path: Path) -> dict | None:
    """读取 .kpak 的 manifest 信息。"""
    import zipfile
    try:
        with zipfile.ZipFile(path, "r") as zf:
            if "manifest.json" in zf.namelist():
                return json.loads(zf.read("manifest.json"))
            # 列出文件结构
            return {"files": zf.namelist()}
    except Exception:
        return None


if __name__ == "__main__":
    main()
