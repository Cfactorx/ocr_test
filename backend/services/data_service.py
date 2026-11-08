"""Label + knowledge-base persistence with corruption safety.

Invariants:
- A corrupt store is never silently reset to ``{}`` and overwritten.
- Every JSON write is atomic (temp file in the same directory + ``os.replace``).
- On corruption the offending file is preserved as a ``.corrupt-*`` backup.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.core.config import Config, load_config

logger = logging.getLogger(__name__)


class DataStoreCorrupted(Exception):
    """A JSON store exists but cannot be parsed."""


def write_json_atomic(path: Path, obj: Any) -> None:
    """Write JSON to ``path`` atomically (same-directory temp + rename)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        os.replace(tmp_name, path)
    except BaseException:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def _read_json(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        raise DataStoreCorrupted(f"Cannot parse {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise DataStoreCorrupted(f"{path} is not a JSON object")
    return data


def _backup_corrupt(path: Path) -> Path | None:
    path = Path(path)
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup = path.with_name(f"{path.name}.corrupt-{stamp}")
    shutil.copy2(path, backup)
    logger.error("Backed up corrupt store %s -> %s", path, backup)
    return backup


class DataService:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or load_config()
        self.labels_dir = self.config.labels_dir
        self.kb_dir = self.config.kb_dir
        self.mapping_file = self.config.labels_file
        self.kb_file = self.config.kb_file
        self._lock = threading.Lock()

        self.labels_dir.mkdir(parents=True, exist_ok=True)
        self.kb_dir.mkdir(parents=True, exist_ok=True)

    def save_label(
        self,
        image_bytes: bytes,
        original_data: dict[str, Any],
        corrected_text: str,
        domain: str = "general",
    ) -> dict[str, Any]:
        """Persist an image + OCR record to labels and the knowledge base."""
        with self._lock:
            self._ensure_stores_readable()

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filename = f"img_{timestamp}.jpg"
            filepath = self.labels_dir / filename

            try:
                with open(filepath, "wb") as f:
                    f.write(image_bytes)

                original_text = str(original_data.get("text", ""))
                is_corrected = original_text.strip() != corrected_text.strip()

                labels = _read_json(self.mapping_file)
                labels[filename] = {
                    "metadata": {
                        "timestamp": timestamp,
                        "domain": domain,
                        "is_corrected": is_corrected,
                    },
                    "ocr_details": {
                        "original_text": original_text,
                        "original_fragments": original_data.get("details", []),
                        "corrected_text": corrected_text,
                    },
                    "tags": [],
                }
                write_json_atomic(self.mapping_file, labels)

                self._save_to_kb(filename, corrected_text, domain, timestamp)
            except BaseException:
                if filepath.exists():
                    filepath.unlink()
                raise

        return {
            "filename": filename,
            "status": "success",
            "type": "correction" if is_corrected else "confirmation",
        }

    def _save_to_kb(self, filename: str, text: str, domain: str, timestamp: str) -> None:
        kb = _read_json(self.kb_file)
        kb[filename] = {
            "text": text,
            "domain": domain,
            "timestamp": timestamp,
            "source_image": filename,
        }
        write_json_atomic(self.kb_file, kb)

    def _ensure_stores_readable(self) -> None:
        """Fail fast (with backups) if either store is corrupt.

        Refuses the whole write rather than silently wiping history.
        """
        try:
            _read_json(self.mapping_file)
            _read_json(self.kb_file)
        except DataStoreCorrupted:
            _backup_corrupt(self.mapping_file)
            _backup_corrupt(self.kb_file)
            raise

    # Read accessors (corruption-safe; replace the old silent-fallback loaders)
    def load_labels(self) -> dict:
        return _read_json(self.mapping_file)

    def load_kb(self) -> dict:
        return _read_json(self.kb_file)
