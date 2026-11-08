"""OCRService pipeline tests (Ollama client is monkeypatched)."""

import asyncio
import json
import sys
import types
from pathlib import Path

import pytest

from backend.core.config import Config
from backend.services.ocr_service import OCRService


def make_service(tmp_path: Path) -> tuple[OCRService, Config]:
    config = Config(data_dir=tmp_path / "data", logs_dir=tmp_path / "logs")
    return OCRService(config), config


def seed_labels(config: Config, records: dict) -> None:
    config.labels_file.parent.mkdir(parents=True, exist_ok=True)
    config.labels_file.write_text(json.dumps(records), encoding="utf-8")


class FakeOllama:
    """Records calls and returns canned responses."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, str]] = []

    def generate(self, model: str, prompt: str, image_b64: str) -> str:
        self.calls.append((model, prompt, image_b64))
        return self.responses.pop(0)


def test_two_pass_pipeline_happy_path(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path)
    fake = FakeOllama(["initial text", "refined text"])
    monkeypatch.setattr(service, "ollama", fake)

    results = asyncio.run(service.recognize_text(b"img-bytes", ".png"))
    assert results == [{"text": "refined text", "confidence": 1.0, "box": [], "refined": True}]
    assert len(fake.calls) == 2
    _, first_prompt, _ = fake.calls[0]
    assert "recognize the text in the provided image" in first_prompt
    _, refine_prompt, _ = fake.calls[1]
    assert "Initial OCR Result" in refine_prompt
    assert "initial text" in refine_prompt


def test_explicit_model_name_used(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path)
    fake = FakeOllama(["first", "second"])
    monkeypatch.setattr(service, "ollama", fake)
    asyncio.run(service.recognize_text(b"img", ".png", model_name="llava"))
    assert fake.calls[0][0] == "llava"


def test_refine_failure_falls_back_to_initial(tmp_path):
    from backend.services.ocr_client import OllamaError

    class FirstPassOnly:
        def generate(self, model: str, prompt: str, image_b64: str) -> str:
            if "Now, please recognize the text" in prompt:
                return "initial text"
            raise OllamaError("refine down")

    service, _ = make_service(tmp_path)
    service.ollama = FirstPassOnly()

    results = asyncio.run(service.recognize_text(b"img-bytes", ".png"))
    assert results[0]["text"] == "initial text"
    assert results[0]["refined"] is False
    assert results[0]["confidence"] == 0.8


def test_first_pass_failure_raises(tmp_path, monkeypatch):
    from backend.services.ocr_client import OllamaError

    service, _ = make_service(tmp_path)

    def boom(model, prompt, image_b64):
        raise OllamaError("connection refused")

    service.ollama = FakeOllama([])
    monkeypatch.setattr(service.ollama, "generate", boom)

    with pytest.raises(RuntimeError, match="首次识别失败"):
        asyncio.run(service.recognize_text(b"img-bytes", ".png"))


def test_corruption_hints_use_last_10_corrections(tmp_path):
    service, config = make_service(tmp_path)
    records = {
        f"img_{i:02d}.jpg": {
            "is_corrected": True,
            "original": f"orig {i}",
            "corrected": f"corr {i}",
        }
        for i in range(15)
    }
    records["img_x.jpg"] = {"is_corrected": False, "original": "o", "corrected": "o"}
    seed_labels(config, records)

    hints = service._get_correction_hints()
    assert "corr 14" in hints
    assert "corr 5" in hints
    assert "corr 4" not in hints  # beyond the most recent 10
    assert "[Correction Knowledge Base]" in hints


def test_hints_support_new_ocr_details_schema(tmp_path):
    service, config = make_service(tmp_path)
    seed_labels(
        config,
        {
            "img_1.jpg": {
                "metadata": {"is_corrected": True},
                "ocr_details": {"original_text": "old", "corrected_text": "new"},
            }
        },
    )
    assert "Original: old" in service._get_correction_hints()


def test_hints_empty_when_no_labels(tmp_path):
    service, _ = make_service(tmp_path)
    assert service._get_correction_hints() == ""


def test_hints_empty_when_labels_corrupt(tmp_path):
    service, config = make_service(tmp_path)
    config.labels_file.parent.mkdir(parents=True, exist_ok=True)
    config.labels_file.write_text("{bad json", encoding="utf-8")
    assert service._get_correction_hints() == ""


def test_get_full_text_joins(tmp_path):
    service, _ = make_service(tmp_path)
    assert service.get_full_text([{"text": "a"}, {"text": "b"}]) == "a\nb"


def test_easyocr_missing_library_raises_runtime_error(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "easyocr", None)  # import of it raises ImportError

    service, _ = make_service(tmp_path)
    fake = FakeOllama(["whatever"])
    monkeypatch.setattr(service, "ollama", fake)

    with pytest.raises(RuntimeError, match="EasyOCR"):
        asyncio.run(service.recognize_text(b"img", ".png", model_name="easyocr"))


def test_easyocr_inference_runs_via_thread(tmp_path, monkeypatch):
    class FakeReader:
        def readtext(self, image_bytes, detail=0):
            return ["line one", "line two"]

    fake_easyocr = types.ModuleType("easyocr")
    fake_easyocr.Reader = lambda *a, **k: FakeReader()
    monkeypatch.setitem(sys.modules, "easyocr", fake_easyocr)

    service, _ = make_service(tmp_path)
    fake = FakeOllama(["refined"])
    monkeypatch.setattr(service, "ollama", fake)

    results = asyncio.run(service.recognize_text(b"img", ".png", model_name="easyocr"))
    assert results[0]["text"] == "refined"
    # easyocr did not call Ollama for the first pass; the only Ollama call is refine
    assert "line one" in fake.calls[0][1]


def test_pdf_without_poppler_config_raises_friendly_error(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path)

    fake_pdf2image = types.ModuleType("pdf2image")

    def convert_from_bytes(*args, **kwargs):
        raise OSError("Unable to get page image: poppler not found")

    fake_pdf2image.convert_from_bytes = convert_from_bytes
    monkeypatch.setitem(sys.modules, "pdf2image", fake_pdf2image)

    with pytest.raises(RuntimeError, match="OCR_POPPLER_PATH"):
        asyncio.run(service.recognize_text(b"%PDF-1.4", ".pdf"))
