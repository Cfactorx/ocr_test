"""One-time migration of legacy label records into the knowledge base.

Paths are anchored to the repository root (not CWD). Any failure exits
non-zero so ops/CI notices instead of the error being swallowed.
"""

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.services.data_service import write_json_atomic  # noqa: E402


def _paths() -> tuple[Path, Path]:
    return (
        _REPO_ROOT / "data" / "labels" / "labels.json",
        _REPO_ROOT / "data" / "knowledge_base" / "kb.json",
    )


def migrate_labels_to_kb() -> int:
    labels_file, kb_file = _paths()

    if not labels_file.exists():
        print(f"No labels file found at {labels_file}. Nothing to migrate.")
        return 0

    print(f"Starting migration from {labels_file} to {kb_file}...")

    try:
        with open(labels_file, "r", encoding="utf-8") as f:
            labels = json.load(f)

        kb: dict = {}
        if kb_file.exists():
            with open(kb_file, "r", encoding="utf-8") as f:
                kb = json.load(f)

        count = 0
        for filename, data in labels.items():
            # Handle both new (ocr_details) and old (flat) schemas
            if "ocr_details" in data:
                corrected_text = (data.get("ocr_details") or {}).get("corrected_text", "")
                domain = (data.get("metadata") or {}).get("domain", "general")
                timestamp = (data.get("metadata") or {}).get("timestamp", "")
            else:
                corrected_text = data.get("text", "")
                domain = "general"
                timestamp = data.get("timestamp", "")

            if corrected_text:
                kb[filename] = {
                    "text": corrected_text,
                    "domain": domain,
                    "timestamp": timestamp,
                    "source_image": filename,
                }
                count += 1

        kb_file.parent.mkdir(parents=True, exist_ok=True)
        with open(kb_file, "w", encoding="utf-8") as f:
            json.dump(kb, f, ensure_ascii=False, indent=2)

        print(f"Successfully migrated {count} samples to knowledge base.")
        return 0
    except Exception as exc:
        print(f"Migration failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(migrate_labels_to_kb())
