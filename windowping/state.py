"""Small persistent state file: what was pinged, when, and what was reported."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path


class State:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.data: dict = {"providers": {}}
        self._load()

    def _load(self) -> None:
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(loaded, dict):
            loaded.setdefault("providers", {})
            self.data = loaded

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data["updated_at"] = time.time()
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    def provider(self, name: str) -> dict:
        return self.data["providers"].setdefault(name, {})

    def update(self, name: str, **values) -> dict:
        entry = self.provider(name)
        entry.update(values)
        return entry

    def already_notified(self, name: str, event: str, key: str | None) -> bool:
        entry = self.provider(name)
        return (entry.get("notified") or {}).get(event) == key

    def mark_notified(self, name: str, event: str, key: str | None) -> None:
        entry = self.provider(name)
        notified = dict(entry.get("notified") or {})
        notified[event] = key
        entry["notified"] = notified


def pid_alive(path: Path) -> bool:
    try:
        pid = int(Path(path).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True
