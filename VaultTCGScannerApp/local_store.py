from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


APP_DIR = Path(os.getenv("LOCALAPPDATA") or (Path.home() / ".vault_tcg_scanner")) / "VaultTCGScanner"


def _path_for(uid: str) -> Path:
    safe_uid = "".join(ch for ch in str(uid) if ch.isalnum() or ch in "-_" ) or "local"
    return APP_DIR / f"pending_{safe_uid}.json"


def load_pending(uid: str) -> list[dict[str, Any]]:
    path = _path_for(uid)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, list) else []
    except Exception:
        return []


def save_pending(uid: str, cards: list[dict[str, Any]]) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    target = _path_for(uid)
    fd, temp_name = tempfile.mkstemp(prefix="pending_", suffix=".json", dir=str(APP_DIR))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(cards, handle, ensure_ascii=False, indent=2)
        os.replace(temp_name, target)
    finally:
        if os.path.exists(temp_name):
            try:
                os.unlink(temp_name)
            except OSError:
                pass
