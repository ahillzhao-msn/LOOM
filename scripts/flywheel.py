#!/usr/bin/env python3
"""
flywheel_job.py — 飞轮任务执行器

管理日常性计划任务：知识摄入、记忆压缩、待办处理、专家模型训练。
由 cron 触发，或由经理按需调用。不处理用户直接输入——那是经理（Agent）的职责。

Usage:
    python flywheel_job.py --job daily              # 每日维护
    python flywheel_job.py --job weekly             # 每周审计
    python flywheel_job.py --job train --domain X   # 训练领域专家
    python flywheel_job.py --backlog                # 处理待办队列
    python flywheel_job.py --check-signals          # 检查训练信号

设计原则：
    - 无硬编码模型名 — 通过 router.find_partners() 发现工人
    - 无硬编码路径 — 所有路径基于 $HOME/.hermes
    - 标准化工具协议 — 工具接收 domain + task_brief，不传模型名
    - 三省记录 — 每个任务完成后记录 self_reflection 维度
"""

import json, sys, subprocess, argparse
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Optional

HOME = Path.home()
HOME = Path.home()
HERE = Path(__file__).resolve().parent

def info(msg: str):
    print(f"[flywheel] {msg}", file=sys.stderr)

# ── 工具脚本路径（旧 skill 已归档至 _deprecated/） ────────
_DEPRECATED = HOME / ".hermes" / "skills" / "human-like" / "core" / "knowledge-management" / "_deprecated" / "tools"
TRAIN_SCRIPT = _DEPRECATED / "model-trainer.py"
BENCHMARK_SCRIPT = _DEPRECATED / "model-benchmark.py"
REGISTER_SCRIPT = _DEPRECATED / "model-register.py"
SFT_GENERATOR = _DEPRECATED / "sft-generator.py"
BACKLOG_SCRIPT = HERE / "backlog.py"

SFT_ROOT = HOME / ".hermes" / "data" / "sft"
SIGNALS_DIR = HOME / ".hermes" / "data" / "training_signals"

def _script_exists(path: Path) -> bool:
    return path.exists()


# ── 入口 ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="飞轮任务执行器")
    parser.add_argument("--job", choices=["daily", "weekly", "train", "backlog", "check-signals"],
                        help="要执行的飞轮任务类型")
    parser.add_argument("--domain", default="", help="领域名（用于 train 任务）")
    parser.add_argument("--context", type=json.loads, default={},
                        help="额外上下文（JSON 对象）")
    args = parser.parse_args()

    if args.job == "daily":
        result = _job_daily(args.context)
    elif args.job == "weekly":
        result = _job_weekly(args.context)
    elif args.job == "train":
        if not args.domain:
            print(json.dumps({"status": "error", "reason": "--domain required for train job"}))
            sys.exit(1)
        result = _job_train(args.domain, args.context)
    elif args.job == "backlog":
        result = _handle_backlog()
    elif args.job == "check-signals":
        result = _check_training_signals()
    else:
        result = {"status": "error", "reason": f"unknown job: {args.job}"}

    print(json.dumps(result, indent=2, ensure_ascii=False))


# ── 每日维护 ────────────────────────────────────────

def _job_daily(ctx: dict) -> Dict:
    """每日维护：知识摄入 → 记忆压缩 → 待办重排 → centroid 重建"""
    steps = {}
    errors = []

    # Step 1: 知识日常摄入
    learn_py = HOME / ".hermes" / "skills" / "human-like" / "core" / "knowledge-management" / "_deprecated" / "learn.py"
    if _script_exists(learn_py):
        rc, out = _run_script(learn_py, ["--mode", "daily"], timeout=120)
        steps["knowledge_daily"] = {"returncode": rc, "output": out[:300]}
        if rc != 0:
            errors.append(f"knowledge_daily failed ({rc})")
    else:
        # fallback: batch_ingest
        batch_sh = HOME / "bin" / "batch_ingest_pdfs.sh"
        if _script_exists(batch_sh):
            rc, out = _run_script(str(batch_sh), [], timeout=300)
            steps["batch_ingest"] = {"returncode": rc, "output": out[:300]}
            if rc != 0:
                errors.append(f"batch_ingest failed ({rc})")

    # Step 2: 记忆压缩（daily-memory-compression）
    # 通过知识管理工具完成

    # Step 3: 待办重排
    if _script_exists(BACKLOG_SCRIPT):
        rc, out = _run_script(str(BACKLOG_SCRIPT), ["--reprioritize"], timeout=30)
        steps["backlog_reprio"] = {"returncode": rc, "output": out[:200]}
        if rc != 0:
            errors.append(f"backlog_reprio failed ({rc})")

    # Step 4: Centroid 重建（新标签已累积一天）
    try:
        KAFED_SRC = HOME / "KAFED" / "src"
        if str(KAFED_SRC) not in sys.path:
            sys.path.insert(0, str(KAFED_SRC))
        from kafed.knowledge.classify.classify import build_centroids
        centroids = build_centroids()
        steps["centroid_rebuild"] = {"domains": len(centroids), "names": list(centroids.keys())}
    except Exception as e:
        errors.append(f"centroid_rebuild failed: {e}")

    status = "ok" if not errors else "partial"
    return {"status": status, "job": "daily", "steps": steps, "errors": errors or None}


# ── 每周审计 ────────────────────────────────────────

def _job_weekly(ctx: dict) -> Dict:
    """每周审计：知识深度维护 → skill 审计 → 训练信号 → 好奇停车场"""
    steps = {}
    errors = []

    # Step 1: 知识每周维护
    learn_py = HOME / ".hermes" / "skills" / "human-like" / "core" / "knowledge-management" / "_deprecated" / "learn.py"
    if _script_exists(learn_py):
        rc, out = _run_script(learn_py, ["--mode", "weekly"], timeout=300)
        steps["knowledge_weekly"] = {"returncode": rc, "output": out[:300]}
        if rc != 0:
            errors.append(f"knowledge_weekly failed ({rc})")

    # Step 2: 检查训练信号并启动训练
    signal_result = _check_training_signals()
    steps["training_signals"] = signal_result
    if signal_result.get("status") == "error":
        errors.append(f"training_signals: {signal_result.get('reason', '?')}")

    # Step 3: 待办清理（标记过期项）
    if _script_exists(BACKLOG_SCRIPT):
        rc, out = _run_script(str(BACKLOG_SCRIPT), ["--reprioritize"], timeout=30)
        steps["backlog_weekly"] = {"returncode": rc, "output": out[:200]}

    status = "ok" if not errors else "partial"
    return {"status": status, "job": "weekly", "steps": steps, "errors": errors or None}


# ── 训练领域专家（飞轮场景） ──────────────────────

def _find_latest_sft(domain: str) -> Path | None:
    """在 SFT_ROOT/{domain}/ 中找最新的 .jsonl"""
    domain_dir = SFT_ROOT / domain
    if not domain_dir.exists():
        return None
    candidates = sorted(domain_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _parse_json_output(out: str) -> dict:
    """尝试解析 stdout 末尾的 JSON 行"""
    for line in reversed(out.strip().split("\n")):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return {}


def _job_train(domain: str, ctx: dict) -> Dict:
    """训练领域专家模型 — 四步管道：SFT生成 → train → benchmark → register

    通过 find_partners() 发现学生模型和教师模型，
    不硬编码模型名。
    """
    steps = {}

    # Step 1: 确保 SFT 数据存在，缺失则自动生成
    sft_jsonl = _find_latest_sft(domain)
    if not sft_jsonl:
        steps["sft_check"] = {"status": "missing", "message": f"No SFT data for {domain}"}
        if _script_exists(SFT_GENERATOR):
            info(f"Auto-triggering SFT generation for {domain}...")
            max_pairs = ctx.get("sft_pairs", 200)
            rc, out = _run_script(SFT_GENERATOR, [
                "--domain", domain,
                "--max-pairs", str(max_pairs),
            ], timeout=1200)
            steps["sft_generation"] = {"returncode": rc, "output": out[:300]}
            if rc == 0:
                sft_jsonl = _find_latest_sft(domain)
        if not sft_jsonl:
            return {"status": "skipped", "job": f"train:{domain}", "steps": steps,
                    "reason": f"SFT generation failed or produced no output for {domain}"}

    steps["sft_check"] = {"status": "found", "path": str(sft_jsonl)}

    # Step 2: 通过 kafed.finder.find_partners() 发现学生和教师模型
    student_model = None
    teacher_model = None
    try:
        sys.path.insert(0, str(HOME / "KAFED" / "src"))
        from kafed.finder.router import find_partners

        student_candidates = find_partners(
            f"为 {domain} 领域训练专家模型，需要一个轻量级学生模型，免费优先",
            budget="free", prefer_local=True, top_k=5)
        teacher_candidates = find_partners(
            f"为 {domain} 领域训练做蒸馏教师，需要高质量的领域知识",
            budget="any", prefer_local=False, top_k=5)

        steps["student_search"] = {
            "count": len(student_candidates.candidates),
            "candidates": [c.name for c in student_candidates.candidates[:3]],
        }
        steps["teacher_search"] = {
            "count": len(teacher_candidates.candidates),
            "candidates": [c.name for c in teacher_candidates.candidates[:3]],
        }

        student = student_candidates.best if student_candidates.candidates else None
        teacher = teacher_candidates.best if teacher_candidates.candidates else None

        if not student:
            return {"status": "skipped", "job": f"train:{domain}", "steps": steps,
                    "reason": "No suitable student model found"}
        student_model = student.name
        teacher_model = teacher.name if teacher else None
        steps["selected_models"] = {"student": student_model, "teacher": teacher_model}

    except Exception as e:
        return {"status": "error", "job": f"train:{domain}",
                "reason": f"find_partners failed: {e}"}

    # Step 3: 训练（model-trainer.py）
    if not _script_exists(TRAIN_SCRIPT):
        return {"status": "error", "reason": f"train script not found: {TRAIN_SCRIPT}"}
    rc, out = _run_script(TRAIN_SCRIPT, [
        "--domain", domain,
        "--base-model", student_model,
        "--data-path", str(sft_jsonl),
    ], timeout=1800)
    steps["training"] = {"returncode": rc, "output": out[:500]}
    if rc != 0:
        return {"status": "error", "job": f"train:{domain}", "steps": steps,
                "reason": f"Training failed ({rc})"}
    train_result = _parse_json_output(out)
    gguf_path = train_result.get("gguf", "")
    model_name = train_result.get("model_name", domain)

    # Step 4: Benchmark（model-benchmark.py）
    benchmark_score = 0.0
    if teacher_model and _script_exists(BENCHMARK_SCRIPT):
        rc, out = _run_script(BENCHMARK_SCRIPT, [
            "--domain", domain,
            "--expert-model", model_name,
            "--teacher", teacher_model,
            "--data-path", str(sft_jsonl),
            "--n", "10",
        ], timeout=300)
        steps["benchmark"] = {"returncode": rc, "output": out[:300]}
        if rc == 0:
            bench_result = _parse_json_output(out)
            benchmark_score = bench_result.get("score", 0.0)
    else:
        steps["benchmark"] = {"skipped": "no teacher model or benchmark script"}
    steps["benchmark_score"] = benchmark_score

    # Step 5: 注册发证（model-register.py）
    if gguf_path and _script_exists(REGISTER_SCRIPT):
        register_args = [
            "--domain", domain,
            "--gguf", gguf_path,
            "--base-model", student_model,
            "--benchmark-score", str(benchmark_score),
            "--pairs", "0",
            "--loss", str(round(5.0 - benchmark_score, 2)) if benchmark_score else "0.0",
        ]
        rc, out = _run_script(REGISTER_SCRIPT, register_args, timeout=60)
        steps["register"] = {"returncode": rc, "output": out[:300]}
        if rc != 0:
            return {"status": "error", "job": f"train:{domain}", "steps": steps,
                    "reason": f"Registration failed ({rc})"}
    else:
        steps["register"] = {"skipped": "no GGUF or register script"}

    return {"status": "ok", "job": f"train:{domain}", "steps": steps}


# ── 检查训练信号 ───────────────────────────────────

def _check_training_signals() -> Dict:
    """检查 SIGNALS_DIR 目录，对每个信号启动训练"""
    if not SIGNALS_DIR.exists():
        return {"status": "ok", "domains": [], "message": "No training signals"}

    launched = []
    errors = []
    for signal in sorted(SIGNALS_DIR.iterdir()):
        if not signal.is_file():
            continue
        domain = signal.name
        result = _job_train(domain, {})
        if result.get("status") == "ok":
            launched.append(domain)
        else:
            errors.append({"domain": domain, "reason": result.get("reason", "?")})
        # 无论成功失败，删除信号文件（避免重复处理）
        signal.unlink(missing_ok=True)

    status = "ok" if not errors else "partial"
    return {"status": status, "domains": launched, "errors": errors or None}


# ── 待办处理 ───────────────────────────────────────

def _handle_backlog() -> Dict:
    """处理待办队列中优先级最高的 pending 项"""
    if not _script_exists(BACKLOG_SCRIPT):
        return {"status": "error", "reason": "backlog.py not found"}

    # 先重排
    _run_script(str(BACKLOG_SCRIPT), ["--reprioritize"], timeout=30)

    # 弹出最高优先项
    rc, out = _run_script(str(BACKLOG_SCRIPT), ["--pop"], timeout=30)
    if rc != 0:
        return {"status": "error", "reason": f"backlog pop failed ({rc})"}

    output = out.strip()
    if "佇列已空" in output or "queue empty" in output.lower():
        return {"status": "ok", "popped": None, "message": "Backlog queue is empty"}

    return {"status": "ok", "popped": output}


# ── 工具函数 ───────────────────────────────────────

def _run_script(script: str, args: list, timeout: int = 60) -> tuple:
    """运行外部脚本，返回 (returncode, stdout)"""
    try:
        res = subprocess.run(
            ["python3", script] + args if script.endswith(".py") else [script] + args,
            capture_output=True, text=True, timeout=timeout
        )
        return res.returncode, res.stdout.strip()
    except subprocess.TimeoutExpired:
        return -1, f"TIMEOUT ({timeout}s)"
    except FileNotFoundError:
        return -2, f"SCRIPT NOT FOUND: {script}"
    except Exception as e:
        return -3, str(e)


if __name__ == "__main__":
    main()
