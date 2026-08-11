"""Tracks the last-seen version/body of each watched Confluence page.

POC-grade JSON file store. Good enough for a single-process deployment;
swap for SQLite (or a real DB) if you need multi-process/concurrent writers.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import TypedDict


class StoredPage(TypedDict):
    page_id: str
    title: str
    version: int
    body_html: str
    body_checksum: str  # sha256 of the normalized plain-text body; see confluence/diff.py
    url: str


class PageStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        if not self._path.exists():
            self._write({})

    def _read(self) -> dict[str, StoredPage]:
        if not self._path.exists():
            return {}
        with self._path.open("r", encoding="utf-8") as f:
            content = f.read().strip()
            return json.loads(content) if content else {}

    def _write(self, data: dict[str, StoredPage]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(".json.tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        tmp_path.replace(self._path)

    def get(self, page_id: str) -> StoredPage | None:
        with self._lock:
            return self._read().get(page_id)

    def put(self, page: StoredPage) -> None:
        with self._lock:
            data = self._read()
            data[page["page_id"]] = page
            self._write(data)
