"""Snapshot store — persists daily asset snapshots as local JSON files."""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)


class SnapshotStore:
    """One JSON file per day under *data_dir*."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, d: date) -> Path:
        return self.data_dir / f"{d.isoformat()}.json"

    def save(self, snapshot_date: date, data: dict) -> Path:
        path = self._path(snapshot_date)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        logger.info("Snapshot saved → %s", path)
        return path

    def load(self, snapshot_date: date) -> dict | None:
        path = self._path(snapshot_date)
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def load_previous(self, before: date) -> dict | None:
        """Load the most recent snapshot strictly before *before*."""
        files = sorted(self.data_dir.glob("*.json"), reverse=True)
        for f in files:
            try:
                file_date = date.fromisoformat(f.stem)
            except ValueError:
                continue
            if file_date < before:
                logger.info("Previous snapshot found: %s", f.name)
                return json.loads(f.read_text())
        logger.info("No previous snapshot found before %s", before)
        return None
