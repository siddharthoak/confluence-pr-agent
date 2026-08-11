"""Append-only history of pipeline runs, for the /ui/runs dashboard.

Same POC-grade JSON file approach as PageStore -- fine for a single process;
swap for SQLite if you need concurrent writers.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict
from pathlib import Path

from confluence_pr_agent.models import RunRecord


class RunStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        if not self._path.exists():
            self._write([])

    def _read(self) -> list[dict]:
        if not self._path.exists():
            return []
        with self._path.open("r", encoding="utf-8") as f:
            content = f.read().strip()
            return json.loads(content) if content else []

    def _write(self, data: list[dict]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(".json.tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        tmp_path.replace(self._path)

    def add_run(self, record: RunRecord) -> None:
        with self._lock:
            data = self._read()
            data.append(asdict(record))
            self._write(data)

    def upsert_run(self, record: RunRecord) -> None:
        """Insert, or update in place if a record with this run_id already
        exists -- used to write a "running" placeholder when a pipeline
        starts and then replace it with the final record when it finishes,
        without ending up with two rows for one invocation.
        """
        with self._lock:
            data = self._read()
            new_record = asdict(record)
            for i, existing in enumerate(data):
                if existing.get("run_id") == record.run_id:
                    data[i] = new_record
                    break
            else:
                data.append(new_record)
            self._write(data)

    def list_runs(self, limit: int = 200) -> list[dict]:
        """Newest first."""
        with self._lock:
            data = self._read()
        return list(reversed(data))[:limit]

    def get_run(self, run_id: str) -> dict | None:
        with self._lock:
            data = self._read()
        for record in reversed(data):
            if record.get("run_id") == run_id:
                return record
        return None

    def delete_run(self, run_id: str) -> bool:
        """Returns True if a matching run was found and deleted."""
        with self._lock:
            data = self._read()
            remaining = [r for r in data if r.get("run_id") != run_id]
            if len(remaining) == len(data):
                return False
            self._write(remaining)
            return True

    def clear_all(self) -> None:
        with self._lock:
            self._write([])
