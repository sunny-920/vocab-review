"""自動備份：每天第一次啟動時複製一份資料庫，保留最近 N 份。"""
import sqlite3
from datetime import datetime

from . import config


def _copy_to(dest) -> None:
    src = sqlite3.connect(config.DB_PATH)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)  # SQLite 線上備份，不會拿到寫到一半的資料
    finally:
        dst.close()
        src.close()


def daily_backup(today: str) -> None:
    if not config.DB_PATH.exists():
        return
    config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    dest = config.BACKUP_DIR / f"vocab-{today}.db"
    if dest.exists():
        return
    _copy_to(dest)
    keep = int(config.load_settings()["backup_keep"])
    daily = sorted(config.BACKUP_DIR.glob("vocab-????-??-??.db"))
    for old in daily[:-keep]:
        old.unlink(missing_ok=True)


def pre_upgrade_backup() -> None:
    """改資料庫結構前額外備份一份（不會被自動清除）。"""
    if not config.DB_PATH.exists():
        return
    config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    _copy_to(config.BACKUP_DIR / f"vocab-before-upgrade-{stamp}.db")
