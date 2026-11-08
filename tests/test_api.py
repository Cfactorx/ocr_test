"""Flask endpoint tests (H3 input boundary + happy path with a faked Ollama)."""

import io
import json
import types

import backend.services.ocr_client as ocr_client
from backend.core.config import Config
from backend.main import create_app, validate_upload
from werkzeug.datastructures import FileStorage


def make_app(tmp_path, max_upload_mb: int = 20):
    config = Config(data_dir=tmp_path / "data", logs_dir=tmp_path / "logs", max_upload_mb=max_upload_mb)
    return create_app(config), config


def upload(app, filename: str, payload: bytes, fields: dict | None = None):
    data = dict(fields or {})
    data["file"] = (io.BytesIO(payload), filename)
    return app.test_client().post(
        "/ocr/recognize", data=data, content_type="multipart/form-data"
    )


def _fake_requests_module():
    class _Resp:
        def __init__(self, text: str):
            self._text = text

        def raise_for_status(self):
            return None

        def json(self):
            return {"response": self._text}

    def post(url, json=None, timeout=None):
        prompt = (json or {}).get("prompt", "")
        text = "initial text" if "Now, please recognize the text" in prompt else "refined text"
        return _Resp(text)

    module = types.ModuleType("fake_requests")
    module.post = post

    class RequestException(Exception):
        pass

    module.RequestException = RequestException
    return module


def patch_ollama(monkeypatch):
    monkeypatch.setattr(ocr_client, "requests", _fake_requests_module())


def test_root_endpoint(tmp_path):
    app, _ = make_app(tmp_path)
    assert app.test_client().get("/").status_code == 200


def test_recognize_missing_file(tmp_path):
    app, _ = make_app(tmp_path)
    response = app.test_client().post(
        "/ocr/recognize", data={}, content_type="multipart/form-data"
    )
    assert response.status_code == 400


def test_recognize_rejects_non_whitelisted_extension(tmp_path):
    app, _ = make_app(tmp_path)
    response = upload(app, "malware.exe", b"MZ...")
    assert response.status_code == 400
    assert "不支持" in response.get_json()["error"]


def test_recognize_rejects_oversized_upload(tmp_path):
    app, _ = make_app(tmp_path, max_upload_mb=1)
    # 1.5MB > 1MB limit, yet the multipart body stays under the +1MB content-length headroom
    response = upload(app, "big.jpg", b"0" * (3 * 1024 * 1024 // 2))
    assert response.status_code == 400
    assert "大小限制" in response.get_json()["error"]


def test_recognize_happy_path(tmp_path, monkeypatch):
    app, _ = make_app(tmp_path)
    patch_ollama(monkeypatch)
    response = upload(app, "doc.jpg", b"jpeg-bytes")
    assert response.status_code == 200
    body = response.get_json()
    assert body["text"] == "refined text"
    assert body["details"][0]["refined"] is True


def test_save_label_rejects_bad_original_data(tmp_path):
    app, _ = make_app(tmp_path)
    response = app.test_client().post(
        "/ocr/save_label",
        data={
            "file": (io.BytesIO(b"x"), "a.jpg"),
            "text": "t",
            "original_data": "not-json",
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 400


def test_save_label_rejects_missing_fields(tmp_path):
    app, _ = make_app(tmp_path)
    response = app.test_client().post(
        "/ocr/save_label", data={}, content_type="multipart/form-data"
    )
    assert response.status_code == 400


def test_save_label_happy_path(tmp_path):
    app, config = make_app(tmp_path)
    response = app.test_client().post(
        "/ocr/save_label",
        data={
            "file": (io.BytesIO(b"imgbytes"), "a.jpg"),
            "text": "corrected",
            "original_data": json.dumps({"text": "original", "details": []}),
            "domain": "general",
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    assert response.get_json()["type"] == "correction"
    labels = json.loads(config.labels_file.read_text(encoding="utf-8"))
    assert len(labels) == 1


def test_validate_upload():
    config = Config(max_upload_mb=1)

    ok_file = FileStorage(stream=io.BytesIO(b"1234"), filename="a.PDF")
    extension, error = validate_upload(ok_file, config)
    assert extension == ".pdf"
    assert error is None

    _, error = validate_upload(FileStorage(stream=io.BytesIO(b"x"), filename="a.exe"), config)
    assert error is not None

    _, error = validate_upload(
        FileStorage(stream=io.BytesIO(b"0" * (2 * 1024 * 1024)), filename="a.jpg"), config
    )
    assert "大小限制" in error

    _, error = validate_upload(FileStorage(stream=io.BytesIO(b"x"), filename=None), config)
    assert error is not None
