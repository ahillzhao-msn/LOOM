"""
KAFED Bootstrap — 環境自適應初始化器。

用法：
  python3 -m kafed.install.bootstrap          # 交互式檢測+安裝
  python3 -m kafed.install.bootstrap --auto    # 全自動（默認值）
  python3 -m kafed.install.bootstrap --hermes  # 裝入 Hermes venv
  python3 -m kafed.install.bootstrap --venv    # 獨立 venv

設計：
  1. 先檢測環境（Hermes/WSL/GPU/llama-server）
  2. 生成 kafed.yaml（自适应注入檢測值）
  3. 創建數據目錄 + 初始化各模塊
  4. 註冊 cron 任務 + 脈動部署（WSL）
  5. 默認裝入 Hermes venv（除非失敗）
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional


# ══════════════════════════════════════════════════
# 環境檢測
# ══════════════════════════════════════════════════


def detect_hermes() -> dict:
    """檢測 Hermes 環境信息。"""
    info = {"available": False, "home": "", "venv_python": "", "config_path": ""}

    # Hermes CLI 可用？
    try:
        r = subprocess.run(["hermes", "--version"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            info["available"] = True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    if not info["available"]:
        # 嘗試從 $HERMES_HOME 檢測
        hermes_home = os.getenv("HERMES_HOME", str(Path.home() / ".hermes"))
        info["home"] = hermes_home

        # 嘗試找到 venv python
        for venv_candidate in [
            Path(hermes_home) / ".venv" / "bin" / "python3",
            Path(hermes_home) / ".venv" / "bin" / "python",
            Path(hermes_home) / "venv" / "bin" / "python3",
        ]:
            if venv_candidate.exists():
                info["venv_python"] = str(venv_candidate)
                break

        config_path = Path(hermes_home) / "config.yaml"
        if config_path.exists():
            info["config_path"] = str(config_path)
    else:
        try:
            r = subprocess.run(["hermes", "config", "show"],
                               capture_output=True, text=True, timeout=10)
            if r.returncode == 0 and r.stdout.strip():
                import yaml
                data = yaml.safe_load(r.stdout) or {}
                hermes_home = data.get("hermes_home", "") or os.getenv("HERMES_HOME",
                                                                       str(Path.home() / ".hermes"))
                info["home"] = str(Path(hermes_home).expanduser())
            else:
                info["home"] = str(Path.home() / ".hermes")
        except Exception:
            info["home"] = str(Path.home() / ".hermes")

        # 從 hermes 獲取 venv python
        try:
            r = subprocess.run(["hermes", "-z", "which python"],
                               capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                info["venv_python"] = r.stdout.strip()
        except Exception:
            pass

        try:
            r = subprocess.run(["hermes", "config", "show"],
                               capture_output=True, text=True, timeout=10)
            if r.returncode == 0 and r.stdout.strip():
                import yaml
                data = yaml.safe_load(r.stdout) or {}
                cf = data.get("config_path", data.get("config_file", ""))
                if cf:
                    info["config_path"] = str(Path(cf).expanduser())
        except Exception:
            pass

    return info


def detect_wsl() -> bool:
    """檢測是否在 WSL 環境。"""
    try:
        with open("/proc/version") as f:
            return "microsoft" in f.read().lower() or "wsl" in f.read().lower()
    except Exception:
        return False


def detect_gpu() -> dict:
    """檢測 GPU 信息。"""
    info = {"available": False, "driver": "", "devices": 0, "memory_mb": 0}
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total",
                            "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            lines = r.stdout.strip().split("\n")
            info["devices"] = len(lines)
            if lines:
                parts = lines[0].split(", ")
                info["name"] = parts[0].strip()
                try:
                    info["memory_mb"] = int(parts[1].strip())
                except (IndexError, ValueError):
                    pass
                info["available"] = True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # 檢測 CUDA 版本
    try:
        r = subprocess.run(["nvcc", "--version"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            for line in r.stdout.split("\n"):
                if "release" in line:
                    info["cuda"] = line.strip()
                    break
    except FileNotFoundError:
        pass

    return info


def detect_llama_server() -> dict:
    """檢測 llama-server 運行狀態。"""
    info = {"running": False, "base_url": "http://localhost:8000", "port": 8000}

    # 嘗試標準端口
    for port in [8000, 8080, 11434]:
        try:
            url = f"http://localhost:{port}"
            r = subprocess.run(
                ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                 "--connect-timeout", "1", "--max-time", "2", f"{url}/health"],
                capture_output=True, text=True, timeout=3,
            )
            if r.stdout.strip().startswith("2"):
                info["running"] = True
                info["base_url"] = url
                info["port"] = port
                break
        except Exception:
            continue

    # 如果默認端口不響應，嘗試查 Hermes config
    if not info["running"]:
        try:
            import yaml
            hermes_home = os.getenv("HERMES_HOME", str(Path.home() / ".hermes"))
            config_path = Path(hermes_home) / "config.yaml"
            if config_path.exists():
                data = yaml.safe_load(config_path.read_text()) or {}
                providers = data.get("providers", {})
                llamacpp = providers.get("llamacpp", {})
                base_url = llamacpp.get("base_url", "")
                if base_url:
                    info["base_url"] = base_url
                    # 提取端口
                    if ":" in base_url:
                        port_str = base_url.rsplit(":", 1)[-1].rstrip("/")
                        try:
                            info["port"] = int(port_str)
                        except ValueError:
                            pass
                    info["running"] = True  # 假設配置的環境連得上
        except Exception:
            pass

    return info


def detect_hermes_providers() -> dict:
    """檢測 Hermes 配置的 provider 列表。"""
    providers = {}
    try:
        import yaml
        hermes_home = os.getenv("HERMES_HOME", str(Path.home() / ".hermes"))
        config_path = Path(hermes_home) / "config.yaml"
        if config_path.exists():
            data = yaml.safe_load(config_path.read_text()) or {}
            prov_cfg = data.get("providers", {})
            for name, cfg in prov_cfg.items():
                if isinstance(cfg, dict):
                    providers[name] = {
                        "base_url": cfg.get("base_url", ""),
                        "models": cfg.get("models", []),
                    }
    except Exception:
        pass
    return providers


# ══════════════════════════════════════════════════
# Config 生成
# ══════════════════════════════════════════════════


def generate_kafed_yaml(
    hermes_info: dict,
    wsl: bool,
    gpu: dict,
    llama: dict,
    providers: dict,
    data_dir: str = "",
) -> str:
    """根據環境檢測結果生成 kafed.yaml 內容。"""
    # 數據目錄
    if not data_dir:
        data_dir = str(Path.home() / ".kafed" / "data")

    # embedding 模型——有 GPU 用大一點的，否則用最小
    embedding_model = "BAAI/bge-small-en-v1.5"
    if gpu.get("available") and gpu.get("devices", 0) > 0:
        # 可以選更好的模型
        pass  # 默認 bge-small 已經很快了

    # 構建 YAML
    lines = []
    lines.append("# KAFED 配置 — 由 kafed-bootstrap 自動生成")
    lines.append(f"# 生成時間: {__import__('datetime').datetime.now().isoformat()}")
    lines.append(f"# 環境: {'WSL' if wsl else 'Linux'}")
    if gpu.get("available"):
        lines.append(f"# GPU: {gpu.get('name', 'Unknown')} "
                     f"({gpu.get('memory_mb', '?')}MB)")
    if llama.get("running"):
        lines.append(f"# llama-server: {llama['base_url']} (running)")
    else:
        lines.append("# llama-server: not detected (offline config)")
    lines.append("")

    lines.append(f"data_dir: {data_dir}")
    lines.append("")

    # ── llama-server ──
    lines.append("# ── llama-server ──")
    if llama.get("running"):
        lines.append(f"llama_server:")
        lines.append(f"  base_url: {llama['base_url']}")
    lines.append("")

    # ── Embedding ──
    lines.append("# ── 嵌入模型 ──")
    lines.append("embedding:")
    lines.append(f"  model: {embedding_model}")
    lines.append(f"  dim: 384")
    # 有 GPU 時可用 cuda
    if gpu.get("available"):
        lines.append("  device: cuda")
    lines.append("")

    # ── Chroma ──
    lines.append("# ── Chroma ──")
    lines.append("chroma:")
    lines.append("  collection: kafed_knowledge")
    lines.append("")

    # ── Finder ──
    lines.append("# ── Finder ──")
    lines.append("finder:")
    lines.append("  freshness_threshold: 0.3")
    lines.append("  context_buffer_size: 500")
    lines.append("  context_boost: 0.15")
    lines.append("  fast_route_max_workers: 3")
    lines.append("  vectors_path: ~/.kafed/worker_vectors.pkl")
    lines.append("  status_cache: ~/.kafed/status_cache.pkl")
    lines.append("")

    # ── Cloud models ──
    lines.append("# ── 雲端模型 ──")
    lines.append("cloud_models:")
    for cm in _cloud_model_defaults(providers):
        lines.append(f"  - name: {cm['name']}")
        lines.append(f"    provider: {cm['provider']}")
        lines.append(f"    is_free: {str(cm.get('is_free', False)).lower()}")
        lines.append(f"    cost: {cm.get('cost', 0.000)}")
        lines.append(f"    context_window: {cm.get('context_window', 128000)}")
        if cm.get("supports_reasoning"):
            lines.append("    supports_reasoning: true")
        if cm.get("supports_vision"):
            lines.append("    supports_vision: true")
        if cm.get("supports_functions"):
            lines.append("    supports_functions: true")
        if cm.get("temperature") is not None:
            lines.append(f"    temperature: {cm['temperature']}")
        lines.append(f"    tags: {cm.get('tags', ['general'])}")
    lines.append("")

    # ── Health endpoints ──
    lines.append("# ── 探活端點 ──")
    lines.append("health_endpoints:")
    lines.append(f"  local: {llama['base_url']}/health")
    if "deepseek" in providers:
        lines.append(f"  deepseek: {providers['deepseek'].get('base_url', 'https://api.deepseek.com/v1')}")
    if "openrouter" in providers:
        lines.append(f"  openrouter: {providers['openrouter'].get('base_url', 'https://openrouter.ai/api/v1/models')}")
    elif "anthropic" in providers:
        lines.append(f"  anthropic: {providers['anthropic'].get('base_url', 'https://api.anthropic.com')}")
    lines.append("")

    # ── Heartbeat ──
    lines.append("# ── Heartbeat ──")
    lines.append("heartbeat:")
    lines.append("  local_base: 10.0")
    lines.append("  cloud_base: 60.0")
    lines.append("  local_max: 120.0")
    lines.append("  cloud_max: 600.0")
    lines.append("  freshness_threshold: 0.3")
    lines.append("")

    # ── 飛輪事件 ──
    lines.append("# ── 飛輪 ──")
    lines.append("flywheel:")
    lines.append("  e1_thresholds: 10,50,100,200,500,1000")
    lines.append("  e2_drift_min: 0.05")
    lines.append("  e3_min_entries: 200")
    lines.append("  e3_repack_growth: 30.0")
    lines.append("  e4_dedup_threshold: 0.95")
    lines.append("  e5_stale_days: 90")
    lines.append("")

    return "\n".join(lines)


def _cloud_model_defaults(providers: dict) -> list[dict]:
    """根據檢測到的 provider 生成默認雲端模型列表。"""
    defaults = []

    if "deepseek" in providers:
        defaults.append({
            "name": "deepseek-v4-flash", "provider": "deepseek",
            "is_free": False, "cost": 0.00015, "context_window": 65536,
            "supports_reasoning": True, "supports_vision": False,
            "supports_functions": True, "temperature": 0.0,
            "tags": ["reasoning", "coding", "fast"],
        })

    if "anthropic" in providers:
        defaults.append({
            "name": "claude-sonnet-4", "provider": "anthropic",
            "is_free": False, "cost": 0.003, "context_window": 200000,
            "supports_reasoning": True, "supports_vision": True,
            "supports_functions": True, "temperature": 0.6,
            "tags": ["reasoning", "analysis", "long_context"],
        })

    if "openai" in providers:
        defaults.append({
            "name": "gpt-4o", "provider": "openai",
            "is_free": False, "cost": 0.0025, "context_window": 128000,
            "supports_reasoning": False, "supports_vision": True,
            "supports_functions": True, "temperature": 0.6,
            "tags": ["reasoning", "vision", "general"],
        })

    if not defaults:
        defaults.append({
            "name": "deepseek-v4-flash", "provider": "deepseek",
            "is_free": False, "cost": 0.00015, "context_window": 65536,
            "supports_reasoning": True, "supports_vision": False,
            "supports_functions": True, "temperature": 0.0,
            "tags": ["reasoning", "coding", "fast"],
        })

    return defaults


# ══════════════════════════════════════════════════
# 目錄創建 + 模塊初始化
# ══════════════════════════════════════════════════


def create_directories(data_dir: str):
    """創建所有 KAFED 數據目錄。"""
    paths = [
        data_dir,
        os.path.join(data_dir, "chroma"),
        os.path.join(data_dir, "feedback_logs"),
        os.path.join(data_dir, "kpak"),
        Path.home() / ".kafed" / "finder_context",
        Path.home() / ".kafed" / "logs",
        Path.home() / ".kafed" / "bin",
    ]
    for p in paths:
        path = Path(p)
        path.mkdir(parents=True, exist_ok=True)
        print(f"  ✓ {path}")


def init_chroma(data_dir: str, collection: str = "kafed_knowledge"):
    """初始化 ChromaDB（創建集合）。"""
    try:
        import chromadb
        chroma_path = os.path.join(data_dir, "chroma")
        client = chromadb.PersistentClient(path=chroma_path)
        # 獲取或創建集合（使用已配置的 embedding 函數）
        from sentence_transformers import SentenceTransformer
        emb_model = SentenceTransformer("BAAI/bge-small-en-v1.5",
                                         device="cpu")
        collection_obj = client.get_or_create_collection(
            name=collection,
            embedding_function=_ChromaEmbedding(emb_model),
        )
        count = collection_obj.count()
        print(f"  ✓ ChromaDB '{collection}': {count} docs -> {chroma_path}")
    except Exception as e:
        print(f"  ⚠ ChromaDB init failed: {e}")


class _ChromaEmbedding:
    """ChromaDB embedding 函數包裝器。"""
    def __init__(self, model):
        self._model = model

    def __call__(self, texts):
        return self._model.encode(list(texts), show_progress_bar=False).tolist()


def init_explorer():
    """運行 Explorer 掃描並初始化向量空間。"""
    try:
        from kafed.finder.explorer import Explorer
        print("  → Scanning models...")
        workers = Explorer.scan_all()
        Explorer.update_vector_space(workers)
        print(f"  ✓ Explorer: {len(workers)} workers -> vector space")
    except Exception as e:
        print(f"  ⚠ Explorer init failed: {e}")


def init_centroids():
    """初始化 centroid 飛輪（最低 seed）。"""
    try:
        from kafed.knowledge.rag.vector_store import VectorStore
        from kafed.knowledge.classify import classify
        vs = VectorStore()
        count = vs.count()
        if count > 0:
            # 有文檔，用 classify 做 seed
            print(f"  ✓ Centroids: {count} docs available (seeded on first classify)")
        else:
            print(f"  · Centroids: skip (empty Chroma, {count} docs)")
    except Exception as e:
        print(f"  ⚠ Centroids init skipped: {e}")


# ══════════════════════════════════════════════════
# Cron / 計劃任務
# ══════════════════════════════════════════════════


def register_crons(hermes_available: bool, is_wsl: bool):
    """註冊 KAFED 定時任務（通過 Hermes cron）。

    頻率設計：
      - Heartbeat:   每 1-2 分鐘（配合內部 backoff，實際探測頻率低於 cron tick）
      - Explorer:    每天凌晨 4 點（模型列表 + 定價，天級變動）
      - Centroids:   每週日凌晨 3 點（聚類中心，週級變動）
    """
    crons = [
        {
            "name": "kafed-heartbeat",
            "schedule": "*/2 * * * *",
            "script": "kafed-heartbeat",
            "desc": "Heartbeat: 每 2 分鐘 tick（內置 backoff 控制實際 probe 頻率）",
        },
        {
            "name": "kafed-explorer",
            "schedule": "0 4 * * *",
            "script": "kafed-explore",
            "desc": "Explorer: 每天 4am 掃描模型 + 更新向量空間 + 定價緩存",
        },
        {
            "name": "kafed-centroids",
            "schedule": "0 3 * * 0",
            "script": "kafed-centroids-rebuild",
            "desc": "Centroids: 每週日凌晨 3 點重建聚類中心",
        },
    ]

    if not hermes_available:
        print("  · Cron: Hermes not available — add crons manually or install Hermes")
        return

    for cron in crons:
        try:
            r = subprocess.run(
                ["hermes", "cron", "list"],
                capture_output=True, text=True, timeout=10,
            )
            if cron["name"] in r.stdout:
                print(f"  · Cron '{cron['name']}' already registered")
                continue

            result = subprocess.run(
                ["hermes", "cron", "create",
                 "--name", cron["name"],
                 "--schedule", cron["schedule"],
                 "--script", cron["script"],
                 ],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                print(f"  ✓ Cron '{cron['name']}': {cron['desc']}")
            else:
                print(f"  ⚠ Cron '{cron['name']}' register failed: {result.stderr[:200]}")
        except Exception as e:
            print(f"  ⚠ Cron '{cron['name']}' error: {e}")


# ══════════════════════════════════════════════════
# 脈動部署（WSL 專用）
# ══════════════════════════════════════════════════


def deploy_pulse_manager(is_wsl: bool, hermes_available: bool):
    """部署 pulse-manager（WSL 環境）。

    WSL 不能 24h 常駐，所以 pulse 是條件觸發式（邏輯 cron 的代理）。
    """
    if not is_wsl:
        return

    if not hermes_available:
        print("  · Pulse: Hermes not available, skip")
        return

    script_path = Path.home() / ".kafed" / "bin" / "pulse-check.py"

    # 寫入 pulse-check 腳本
    script_content = """#!/usr/bin/env python3
\"\"\"KAFED Pulse Check — WSL 脈動探測器。

每次 tick = 檢查所有到期任務。不常駐——由 Hermes cron（每 15min）喚醒。
KAFED 已 pip install -e 安裝，直接 import 即可。
\"\"\"
import sys
from pathlib import Path

try:
    from kafed.finder.heartbeat import Heartbeat
    hb = Heartbeat()
    n = hb.tick()
    print(f"pulse: {n} models probed")
except ImportError:
    # 若未 pip 安裝，從源碼樹 fallback
    sys.path.insert(0, str(Path.home() / "KAFED" / "src"))
    from kafed.finder.heartbeat import Heartbeat
    hb = Heartbeat()
    n = hb.tick()
    print(f"pulse: {n} models probed (source fallback)")
except Exception as e:
    print(f"pulse: error -> {e}")
"""
    try:
        script_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.write_text(script_content)
        script_path.chmod(0o755)
        print(f"  ✓ Pulse script: {script_path}")
    except Exception as e:
        print(f"  ⚠ Pulse script failed: {e}")

    # 註冊 pulse cron（每 15 分鐘）
    try:
        r = subprocess.run(
            ["hermes", "cron", "list"],
            capture_output=True, text=True, timeout=10,
        )
        if "kafed-pulse" in r.stdout:
            print("  · Pulse cron already registered")
            return

        subprocess.run(
            ["hermes", "cron", "create",
             "--name", "kafed-pulse",
             "--schedule", "*/15 * * * *",
             "--script", str(script_path),
             ],
            capture_output=True, text=True, timeout=10,
        )
        print(f"  ✓ Pulse cron registered (every 15 min)")
    except Exception as e:
        print(f"  ⚠ Pulse cron failed: {e}")


# ══════════════════════════════════════════════════
# Hermes venv 安裝
# ══════════════════════════════════════════════════


def install_into_hermes(hermes_info: dict, project_root: str) -> bool:
    """將 KAFED 安裝到 Hermes 的 venv 中。

    使用 Hermes venv 的 pip 執行 pip install -e .
    """
    venv_python = hermes_info.get("venv_python", "")
    if not venv_python or not Path(venv_python).exists():
        # 嘗試自動發現
        hermes_home = hermes_info.get("home", str(Path.home() / ".hermes"))
        candidates = [
            hermes_home + "/.venv/bin/python3",
            hermes_home + "/.venv/bin/python",
            hermes_home + "/venv/bin/python3",
        ]
        for c in candidates:
            if Path(c).exists():
                venv_python = c
                break

    if not venv_python:
        print("  ⚠ Cannot find Hermes venv Python — will install standalone")
        return False

    pip_args = [venv_python, "-m", "pip", "install", "-e", project_root]
    try:
        r = subprocess.run(
            pip_args,
            capture_output=True, text=True, timeout=120,
        )
        if r.returncode == 0:
            print(f"  ✓ KAFED installed into Hermes venv: {venv_python}")
            # 驗證導入
            verify = subprocess.run(
                [venv_python, "-c", "import kafed; print(kafed.__version__)"],
                capture_output=True, text=True, timeout=10,
            )
            if verify.returncode == 0:
                ver = verify.stdout.strip()
                print(f"  ✓ Verification: import kafed -> v{ver}")
            return True
        else:
            print(f"  ⚠ pip install failed: {r.stderr[:200]}")
            return False
    except Exception as e:
        print(f"  ⚠ pip install error: {e}")
        return False


# ══════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════


# ══════════════════════════════════════════════════
# Hermes 工具集成
# ══════════════════════════════════════════════════


def _install_kafed_tool_symlink(hermes_available: bool):
    """創建 KAFED Hermes tool symlink（軟性——失敗不中斷）。

    將 src/kafed/client/kafed_tool.py 鏈接到 Hermes tools/ 目錄，
    使 kafed_query / kafed_ingest / kafed_status / kafed_classify 可用。
    """
    if not hermes_available:
        print("  · KAFED tool: Hermes not available, skip")
        return

    project_root = Path(__file__).resolve().parent.parent.parent.parent  # src/ → project root
    tool_src = project_root / "src" / "kafed" / "client" / "kafed_tool.py"
    if not tool_src.exists():
        print("  · kafed_tool.py not found, skip Hermes integration")
        return

    hermes_home = os.getenv("HERMES_HOME", str(Path.home() / ".hermes"))
    tool_dst = Path(hermes_home) / "hermes-agent" / "tools" / "kafed_tool.py"
    tool_dst.parent.mkdir(parents=True, exist_ok=True)

    try:
        if tool_dst.exists() or tool_dst.is_symlink():
            tool_dst.unlink()
        tool_dst.symlink_to(str(tool_src))
        print(f"  ✓ KAFED tool linked: {tool_dst}")
    except Exception as e:
        print(f"  ⚠ KAFED tool link failed: {e}")


def _install_yicenet_soft(target_python: str = ""):
    """安裝 YiCeNet 依賴（軟性——失敗繼續不中斷）。

    從 GitHub 克隆（如果本地不存在），然後調用其 bootstrap。
    """
    yicenet_dir = Path.home() / "YiCeNet"

    try:
        # 1. 確保 YiCeNet 源碼存在
        if not yicenet_dir.exists() or not (yicenet_dir / "pyproject.toml").exists():
            print("  → Cloning YiCeNet from GitHub...")
            r = subprocess.run(
                ["git", "clone", "https://github.com/ahillzhao-msn/YiCeNet.git",
                 str(yicenet_dir)],
                capture_output=True, text=True, timeout=60,
            )
            if r.returncode != 0:
                print(f"  ⚠ YiCeNet clone failed (soft skip): {r.stderr[:100]}")
                return
            print("  ✓ YiCeNet cloned")

        # 2. 調用 YiCeNet 的 bootstrap（使用包內入口，非 scripts/ 腳本）
        # 先確保已安裝為 editable package，然後用 CLI 入口
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "-e", str(yicenet_dir)],
                capture_output=True, text=True, timeout=60,
            )
        except Exception:
            pass

        cmd = [sys.executable, "-m", "yicenet.bootstrap", "--auto"]
        if target_python:
            cmd += ["--venv", target_python]
        cmd += ["--skip-hermes"]  # Hermes 工具鏈接由 KAFED bootstrap 管理

        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        for line in r.stdout.split("\n"):
            if line.strip() and ("✓" in line or "⚠" in line or "Phase" in line or "Error" in line):
                print(f"   {line.strip()}")
        if r.returncode != 0:
            print(f"  ⚠ YiCeNet bootstrap had issues (soft — continue)")
        else:
            print("  ✓ YiCeNet initialized")

    except Exception as e:
        print(f"  ⚠ YiCeNet install skipped (soft): {e}")


def bootstrap(auto: bool = False, hermes: bool = False,
              venv: bool = False, data_dir: str = "",
              skip_cron: bool = False, skip_install: bool = False):
    """執行完整初始化流程。"""
    print()
    print("╔══════════════════════════════════════════╗")
    print("║  KAFED Bootstrap — 環境自適應初始化     ║")
    print("╚══════════════════════════════════════════╝")
    print()

    # ── Phase 1: 環境檢測 ──
    print("── Phase 1: 環境檢測 ──")
    hermes_info = detect_hermes()
    is_wsl = detect_wsl()
    gpu = detect_gpu()
    llama = detect_llama_server()
    providers = detect_hermes_providers()

    print(f"  Hermes:        {'✓ available' if hermes_info['available'] else '✗ not found'}")
    print(f"  WSL:           {'✓' if is_wsl else '✗'}")
    print(f"  GPU:           {'✓ ' + gpu.get('name', '') + ' (' + str(gpu.get('memory_mb', '?')) + 'MB)' if gpu.get('available') else '✗ no GPU'}")
    print(f"  llama-server:  {'✓ ' + llama['base_url'] if llama.get('running') else '✗ not running'}")
    print(f"  Providers:     {', '.join(providers.keys()) if providers else 'none detected'}")
    print()

    # ── Phase 2: Config 生成 ──
    print("── Phase 2: Config 生成 ──")
    config_content = generate_kafed_yaml(
        hermes_info, is_wsl, gpu, llama, providers, data_dir,
    )

    config_path = Path.home() / ".kafed" / "kafed.yaml"
    if config_path.exists() and not auto:
        resp = input(f"  {config_path} 已存在。覆寫？[y/N] ").strip().lower()
        if resp != "y":
            print("  · Skipped (existing config preserved)")
        else:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(config_content)
            print(f"  ✓ {config_path}")
    elif auto or not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(config_content)
        print(f"  ✓ {config_path}")
    print()

    # ── Phase 3: 目錄創建 + 模塊初始化 ──
    print("── Phase 3: 目錄 & 模塊初始化 ──")
    resolved_data = data_dir or str(Path.home() / ".kafed" / "data")
    create_directories(resolved_data)
    print()

    print("  → 初始化 ChromaDB...")
    init_chroma(resolved_data)

    print("  → 初始化 Explorer 向量空間...")
    init_explorer()

    print("  → 初始化 Centroids...")
    init_centroids()
    print()

    # ── Phase 4: Cron 註冊 ──
    if not skip_cron:
        print("── Phase 4: Cron 註冊 ──")
        register_crons(hermes_info["available"], is_wsl)
        deploy_pulse_manager(is_wsl, hermes_info["available"])
        print()
    else:
        print("── Phase 4: Cron (skipped) ──")
        print()

    # ── Phase 5: 安裝到 Hermes venv ──
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    project_root = os.path.dirname(project_root)  # kafed/ -> src/ -> project root

    if not skip_install:
        print("── Phase 5: 安裝 ──")
        if hermes or (not venv and not skip_install):
            installed = install_into_hermes(hermes_info, project_root)
            if not installed and venv:
                print("  → Falling back to standalone venv...")
                # future: standalone venv creation
        elif venv:
            print("  → Standalone venv install (future)")

        # KAFED Hermes tool symlink (optional)
        _install_kafed_tool_symlink(hermes_info.get("available", False))
        print()
    else:
        print("── Phase 5: Install (skipped) ──")
        print()

    # ── Phase 6: YiCeNet（依賴項目，軟性安裝）──
    print("── Phase 6: YiCeNet 依賴 ──")
    _install_yicenet_soft(target_python=hermes_info.get("venv_python", ""))
    print()

    # ── 完成 ──
    print("╔══════════════════════════════════════════╗")
    print("║  KAFED Bootstrap 完成！                  ║")
    print("╚══════════════════════════════════════════╝")
    print()
    print("  驗證安裝:")
    print(f"    python3 -c \"import kafed; print(kafed.__version__)\"")
    print(f"    kafed-heartbeat")
    print()
    print("  配置位置:")
    print(f"    ~/.kafed/kafed.yaml")
    print()
    print("  數據目錄:")
    print(f"    {resolved_data}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="KAFED Bootstrap — 環境自適應初始化",
    )
    parser.add_argument("--auto", action="store_true",
                        help="全自動（不提示，使用默認值）")
    parser.add_argument("--hermes", action="store_true",
                        help="裝入 Hermes venv（默認）")
    parser.add_argument("--venv", action="store_true",
                        help="使用獨立 venv")
    parser.add_argument("--data-dir", default="",
                        help="KAFED 數據目錄（默認 ~/.kafed/data）")
    parser.add_argument("--skip-cron", action="store_true",
                        help="跳過 cron 註冊")
    parser.add_argument("--skip-install", action="store_true",
                        help="跳過 pip install")

    args = parser.parse_args()
    bootstrap(
        auto=args.auto,
        hermes=args.hermes or not args.venv,  # 默認 Hermes
        venv=args.venv,
        data_dir=args.data_dir,
        skip_cron=args.skip_cron,
        skip_install=args.skip_install,
    )


if __name__ == "__main__":
    main()
