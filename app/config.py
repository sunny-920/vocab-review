"""路徑與設定。所有資料都放在專案的 data\\ 資料夾。"""
import json
import os
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 開發測試用：設定 VOCAB_DATA 可以改用別的資料夾，不會動到你真正的單字資料
DATA = Path(os.environ["VOCAB_DATA"]) if os.environ.get("VOCAB_DATA") else ROOT / "data"
DB_PATH = DATA / "vocab.db"
DICT_PATH = ROOT / "data" / "ecdict_lite.db"  # 字典固定在專案裡（唯讀）
BACKUP_DIR = DATA / "backups"
SETTINGS_PATH = DATA / "settings.json"
STATIC = Path(__file__).resolve().parent / "static"

HOST = "127.0.0.1"  # 只接受本機連線
PORT = int(os.environ.get("VOCAB_PORT") or 8765)

DEFAULTS = {
    "model": "qwen3:8b",
    "ollama_url": "http://127.0.0.1:11434",
    "day_start_hour": 4,   # 凌晨 4 點才換日
    "daily_limit": 30,     # 每日複習一輪幾個
    "backup_keep": 7,      # 保留幾份每日備份
}

_LIMITS = {
    "day_start_hour": (0, 12),
    "daily_limit": (5, 500),
    "backup_keep": (1, 60),
}

_lock = threading.Lock()


def load_settings() -> dict:
    with _lock:
        data = dict(DEFAULTS)
        if SETTINGS_PATH.exists():
            try:
                saved = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
                data.update({k: v for k, v in saved.items() if k in DEFAULTS})
            except (OSError, ValueError):
                pass
        return data


def save_settings(patch: dict) -> dict:
    current = load_settings()
    for key, value in patch.items():
        if key not in DEFAULTS:
            continue
        if key in _LIMITS:
            lo, hi = _LIMITS[key]
            value = max(lo, min(hi, int(value)))
        else:
            value = str(value).strip() or DEFAULTS[key]
        current[key] = value
    with _lock:
        DATA.mkdir(exist_ok=True)
        SETTINGS_PATH.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    return current
