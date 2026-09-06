import os
from pathlib import Path

FILE = Path(__file__).resolve().parent / "authorized_users.txt"


def _load_ids():
    ids = set()
    if FILE.exists():
        for line in FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                ids.add(int(line))
            except ValueError:
                pass
    return ids


def _env_ids():
    ids = set()
    raw = os.getenv("ADMIN_IDS", "")
    for value in raw.replace(";", ",").split(","):
        value = value.strip()
        if value:
            try:
                ids.add(int(value))
            except ValueError:
                pass
    return ids


def authorized(user_id: int) -> bool:
    file_ids = _load_ids()
    if file_ids:
        return user_id in file_ids
    return user_id in _env_ids()

