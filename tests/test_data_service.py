"""DataService corruption safety: the C1 data-loss defect must not recur."""

import json
from pathlib import Path

import pytest

from backend.core.config import Config
from backend.services.data_service import (
    DataService,
    DataStoreCorrupted,
    _read_json,
    write_json_atomic,
)


def make_service(tmp_path: Path, **kwargs) -> tuple[DataService, Config]:
    config = Config(
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        **kwargs,
    )
    return DataService(config), config


def test_save_label_writes_image_and_merges_records(tmp_path):
    service, config = make_service(tmp_path)

    result = service.save_label(b"img-bytes", {"text": "a", "details": []}, "a")
    assert result["status"] == "success"
    assert result["type"] == "confirmation"

    labels = json.loads(config.labels_file.read_text(encoding="utf-8"))
    assert result["filename"] in labels
    record = labels[result["filename"]]
    assert record["ocr_details"]["original_text"] == "a"
    assert record["metadata"]["is_corrected"] is False

    kb = json.loads(config.kb_file.read_text(encoding="utf-8"))
    assert kb[result["filename"]]["text"] == "a"


def test_save_label_correction_type(tmp_path):
    service, _ = make_service(tmp_path)
    result = service.save_label(b"img-bytes", {"text": "a"}, "b")
    assert result["type"] == "correction"
    labels = json.loads(service.config.labels_file.read_text(encoding="utf-8"))
    assert labels[result["filename"]]["metadata"]["is_corrected"] is True


def test_corrupt_labels_refuses_write_and_preserves_data(tmp_path):
    service, config = make_service(tmp_path)
    service.save_label(b"x", {"text": "old"}, "old")  # seed a good record

    config.labels_file.write_text("{not json!!", encoding="utf-8")

    with pytest.raises(DataStoreCorrupted):
        service.save_label(b"y", {"text": "new"}, "new")

    # Original corrupt content must still be there (backed up, not wiped)
    assert config.labels_file.read_text(encoding="utf-8") == "{not json!!"
    backups = list(config.labels_dir.glob("labels.json.corrupt-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "{not json!!"

    # And the corrupt content is still the on-disk truth -> no silent data loss
    with pytest.raises(DataStoreCorrupted):
        service.load_labels()


def test_corrupt_kb_refuses_write(tmp_path):
    service, config = make_service(tmp_path)
    config.kb_file.write_text("[", encoding="utf-8")
    with pytest.raises(DataStoreCorrupted):
        service.save_label(b"x", {"text": "a"}, "a")
    backups = list(config.kb_dir.glob("kb.json.corrupt-*"))
    assert len(backups) == 1


def test_read_json_missing_returns_empty(tmp_path):
    assert _read_json(tmp_path / "nope.json") == {}


def test_read_json_non_dict_raises(tmp_path):
    target = tmp_path / "list.json"
    target.write_text("[1,2]", encoding="utf-8")
    with pytest.raises(DataStoreCorrupted):
        _read_json(target)


def test_write_json_atomic_creates_parents_and_no_tmp_left(tmp_path):
    target = tmp_path / "a" / "b" / "x.json"
    write_json_atomic(target, {"k": "v"})
    assert json.loads(target.read_text(encoding="utf-8")) == {"k": "v"}
    leftovers = list(tmp_path.glob("a/b/.tmp-*"))
    assert leftovers == []


def test_repeated_saves_accumulate_records(tmp_path):
    service, config = make_service(tmp_path)
    for _ in range(3):
        service.save_label(b"x", {"text": "a"}, "a")
    labels = json.loads(config.labels_file.read_text(encoding="utf-8"))
    assert len(labels) == 3
