"""Daily SQLite snapshots.

Uses SQLite's online backup API, which produces a consistent copy even while
the app is serving requests. Runs from `flask backup-db` (e.g. a scheduled
task) and automatically once a day from the app itself as a safety net.
"""

import logging
import sqlite3
import threading
from datetime import date
from pathlib import Path

log = logging.getLogger(__name__)

PREFIX = "spendly-"
_lock = threading.Lock()
_last_checked = None


def backup_path(backup_dir, day):
    return Path(backup_dir) / f"{PREFIX}{day.isoformat()}.db"


def create_backup(db_path, backup_dir, keep=14, day=None):
    """Snapshot db_path into backup_dir for `day` and prune old snapshots.

    Returns the snapshot path. Overwrites an existing snapshot for the same day.
    """
    day = day or date.today()
    target_dir = Path(backup_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = backup_path(target_dir, day)
    tmp = target.with_suffix(".tmp")

    src = sqlite3.connect(db_path)
    try:
        dst = sqlite3.connect(tmp)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    tmp.replace(target)  # atomic: a half-written file never looks like a backup

    snapshots = sorted(target_dir.glob(f"{PREFIX}*.db"))
    for old in snapshots[:-keep] if keep > 0 else []:
        old.unlink(missing_ok=True)
    return target


def list_backups(backup_dir):
    return sorted(Path(backup_dir).glob(f"{PREFIX}*.db"), reverse=True)


def ensure_daily_backup(db_path, backup_dir, keep, day=None):
    """Create today's snapshot if it doesn't exist yet. Cheap after the first call per day."""
    global _last_checked
    day = day or date.today()
    if _last_checked == (str(backup_dir), day):
        return None
    with _lock:
        if _last_checked == (str(backup_dir), day):
            return None
        _last_checked = (str(backup_dir), day)
        if backup_path(backup_dir, day).exists() or not Path(db_path).exists():
            return None
        try:
            return create_backup(db_path, backup_dir, keep, day)
        except (OSError, sqlite3.Error):
            log.exception("Automatic backup failed")
            return None


def reset_daily_check():
    global _last_checked
    _last_checked = None
