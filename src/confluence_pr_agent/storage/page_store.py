"""Tracks the last-seen version/body of each watched Confluence page.

POC-grade JSON file store. Good enough for a single-process deployment;
swap for SQLite (or a real DB) if you need multi-process/concurrent writers.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import NotRequired, TypedDict


class StoredPage(TypedDict):
    page_id: str
    title: str
    version: int
    body_html: str
    body_checksum: str  # sha256 of the normalized plain-text body; see confluence/diff.py
    url: str
    # Tracks the most recent PR opened for this page, if it's still open --
    # lets the next run reuse/update it instead of opening a duplicate PR
    # when the spec changes again before that PR is merged. Absent/None once
    # that PR is merged or closed (checked fresh each run via the GitHub
    # API, not assumed from this cache alone). See pipeline/orchestrator.py.
    open_pr_number: NotRequired[int | None]
    open_pr_branch: NotRequired[str | None]
    # Same idea, for the Jira story tracking this page (JIRA_ENABLED) -- the
    # next run comments on it instead of creating a duplicate while it's
    # still open. See pipeline/orchestrator.py.
    jira_issue_key: NotRequired[str | None]


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
