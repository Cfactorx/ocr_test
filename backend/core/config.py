"""Central configuration for the OCR service.

All environment overrides use the OCR_ prefix. Path defaults are anchored
to the repository root so the service works regardless of the current
working directory.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

# backend/core/config.py -> parents[2] == repository root
_REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "gemma4:31b-cloud"
DEFAULT_CORS_ORIGINS = "http://localhost:5500,http://127.0.0.1:5500"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080
DEFAULT_MAX_UPLOAD_MB = 20


@dataclass(frozen=True)
class Config:
    """Frozen runtime configuration. Mutate by building a new instance."""

    ollama_url: str = DEFAULT_OLLAMA_URL
    default_model: str = DEFAULT_MODEL
    data_dir: Path = _REPO_ROOT / "data"
    logs_dir: Path = _REPO_ROOT / "logs"
    poppler_path: str | None = None
    cors_origins: str = DEFAULT_CORS_ORIGINS
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    max_upload_mb: int = DEFAULT_MAX_UPLOAD_MB

    @property
    def labels_dir(self) -> Path:
        return self.data_dir / "labels"

    @property
    def kb_dir(self) -> Path:
        return self.data_dir / "knowledge_base"

    @property
    def labels_file(self) -> Path:
        return self.labels_dir / "labels.json"

    @property
    def kb_file(self) -> Path:
        return self.kb_dir / "kb.json"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


def _int_env(e: Mapping[str, str], key: str, default: int, what: str) -> int:
    raw = e.get(key)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"环境变量 {key} 必须是整数（{what}），当前值: {raw!r}") from exc
    if value <= 0:
        raise ValueError(f"环境变量 {key} 必须为正数（{what}），当前值: {value}")
    return value


def load_config(env: Mapping[str, str] | None = None) -> Config:
    """Build a Config from environment variables (or an explicit mapping)."""
    e = os.environ if env is None else env

    data_dir = Path(e["OCR_DATA_DIR"]).expanduser() if e.get("OCR_DATA_DIR") else _REPO_ROOT / "data"
    logs_dir = Path(e["OCR_LOG_DIR"]).expanduser() if e.get("OCR_LOG_DIR") else _REPO_ROOT / "logs"

    return Config(
        ollama_url=e.get("OCR_OLLAMA_URL", DEFAULT_OLLAMA_URL),
        default_model=e.get("OCR_DEFAULT_MODEL", DEFAULT_MODEL),
        data_dir=data_dir,
        logs_dir=logs_dir,
        poppler_path=e.get("OCR_POPPLER_PATH") or None,
        cors_origins=e.get("OCR_CORS_ORIGINS", DEFAULT_CORS_ORIGINS),
        host=e.get("OCR_HOST", DEFAULT_HOST),
        port=_int_env(e, "OCR_PORT", DEFAULT_PORT, "端口号"),
        max_upload_mb=_int_env(e, "OCR_MAX_UPLOAD_MB", DEFAULT_MAX_UPLOAD_MB, "上传上限"),
    )
