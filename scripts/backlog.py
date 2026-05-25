#!/usr/bin/env python3
"""
backlog.py — 內部待辦佇列管理（CLI）

底層由 kafed.knowledge.backlog 提供。依賴同一份 backlog.json。

用法:
  python backlog.py              # 顯示優先排序的佇列
  python backlog.py --pop        # 取出最高優先的 pending 項
  python backlog.py --add TITLE VALUE URGENCY  # 新增事項
  python backlog.py --done <id>  # 標記完成
  python backlog.py --reprioritize  # 重新計算所有 priority_score
"""

import json, sys, argparse
from pathlib import Path
from datetime import datetime, timezone

# 路徑跟隨 config（非硬編碼）
try:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from kafed.config import get_config
    BACKLOG_PATH = get_config().backlog_data
except ImportError:
    BACKLOG_PATH = Path.home() / ".hermes" / "data" / "backlog.json"

def load():
    if BACKLOG_PATH.exists():
        with open(BACKLOG_PATH) as f:
            return json.load(f)
    return {"version": 2, "items": [], "formula": {}, "categories": {}, "history": []}

def save(bl):
    bl["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(BACKLOG_PATH, "w") as f:
        json.dump(bl, f, indent=2, ensure_ascii=False)

def reprioritize(bl):
    """重新計算所有 priority_score"""
    formula = bl.get("formula", {})
    # priority = value * w1 + urgency * w2
    lines = formula.get("priority_score", "value_weight * 0.6 + temporal_priority * 0.4")
    # parse: extract weights
    import re
    m = re.search(r'value_weight\s*\*\s*([\d.]+)', lines)
    w1 = float(m.group(1)) if m else 0.6
    m = re.search(r'temporal_priority\s*\*\s*([\d.]+)', lines)
    w2 = float(m.group(1)) if m else 0.4
    
    now = datetime.now(timezone.utc)
    for item in bl["items"]:
        v = item.get("value_weight", 0.5)
        t = item.get("temporal_priority", 0.5)
        # 自動提升：item 存在超過 auto_promote_days 未處理，逐漸提升 temporal
        days_existed = (now - datetime.fromisoformat(item.get("created_at", now.isoformat()))).days
        auto_days = bl.get("formula", {}).get("auto_promote_days", 14)
        if days_existed > auto_days and item["status"] == "pending":
            boost = min(0.3, (days_existed - auto_days) * 0.02)
            t = min(1.0, t + boost)
        item["priority_score"] = round(v * w1 + t * w2, 3)
    
    return bl

def show(bl, limit=15):
    items = [i for i in bl["items"] if i["status"] != "done"]
    items.sort(key=lambda x: x.get("priority_score", 0), reverse=True)
    
    if not items:
        print("  (queue empty)")
        return
    
    print(f"内部待辦佇列 ({len(items)} pending)")
    print(f"公式: {bl.get('formula', {}).get('priority_score', '?')}")
    print(f"{' ':<6} {'優先':<6} {'價值':<6} {'時效':<6} {'耗時':<8} {'事項':<40} {'類別':<10}")
    print("-" * 85)
    for i, item in enumerate(items[:limit]):
        ps = item.get("priority_score", 0)
        v = item.get("value_weight", 0)
        t = item.get("temporal_priority", 0)
        effort = item.get("effort", "?")
        title = item.get("title", "?")[:38]
        cat = item.get("category", "?")
        marker = "★" if ps > 0.6 else "∙" if ps > 0.4 else " "
        deps = item.get("dependencies", [])
        dep_mark = " ⛓" if deps else ""
        print(f"  {i:<3} {ps:<.3f} {v:<.3f} {t:<.3f} {effort:<8} {marker} {title:<38}{dep_mark} [{cat}]")

def main():
    parser = argparse.ArgumentParser(description="內部待辦佇列")
    parser.add_argument("--pop", action="store_true", help="取出最高優先事項")
    parser.add_argument("--add", nargs=3, metavar=("TITLE", "VALUE", "URGENCY"),
                        help="新增事項 (title value_weight temporal_priority)")
    parser.add_argument("--done", help="標記事項完成 (id)")
    parser.add_argument("--reprioritize", action="store_true", help="重新計算優先級")
    parser.add_argument("--all", action="store_true", help="顯示全部（含 completed）")
    args = parser.parse_args()
    
    bl = load()
    
    if args.reprioritize:
        bl = reprioritize(bl)
        save(bl)
        print("✅ 優先級已重新計算")
    
    if args.pop:
        items = [i for i in bl["items"] if i["status"] == "pending"]
        items.sort(key=lambda x: x.get("priority_score", 0), reverse=True)
        if items:
            top = items[0]
            # update status to in_progress
            for item in bl["items"]:
                if item["id"] == top["id"]:
                    item["status"] = "in_progress"
                    item["updated_at"] = datetime.now(timezone.utc).isoformat()
                    break
            save(bl)
            print(f"取出: [{top['priority_score']:.3f}] {top['title']}")
            print(f"  描述: {top.get('description', '?')}")
            print(f"  耗時: {top.get('effort', '?')}  依賴: {top.get('dependencies', [])}")
        else:
            print("佇列已空")
    
    if args.done:
        for item in bl["items"]:
            if item["id"] == args.done:
                item["status"] = "done"
                item["updated_at"] = datetime.now(timezone.utc).isoformat()
                bl.setdefault("history", []).append({
                    "action": "completed",
                    "id": args.done,
                    "title": item["title"],
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
                save(bl)
                print(f"✅ {item['title']} — 已完成")
                break
        else:
            print(f"❌ 未找到 id: {args.done}")
    
    if args.add:
        title, v_str, t_str = args.add
        v = float(v_str)
        t = float(t_str)
        existing_ids = [i["id"] for i in bl["items"]]
        # find next id
        nums = [int(i.split("_")[1]) for i in existing_ids if i.startswith("backlog_")]
        next_num = max(nums) + 1 if nums else 1
        ps = round(v * 0.6 + t * 0.4, 3)
        item = {
            "id": f"backlog_{next_num:03d}",
            "title": title,
            "description": "",
            "category": "infra",
            "value_weight": v,
            "temporal_priority": t,
            "priority_score": ps,
            "effort": "?",
            "dependencies": [],
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "tags": [],
            "notes": ""
        }
        bl["items"].append(item)
        save(bl)
        print(f"✅ 新增: [{ps:.3f}] {title}")
    
    if not any([args.pop, args.done, args.add, args.reprioritize]):
        # 先重新計算
        bl = reprioritize(bl)
        save(bl)
        show(bl, limit=20 if args.all else 15)

if __name__ == "__main__":
    main()
