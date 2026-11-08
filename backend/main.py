"""Flask application entry point for the OCR service."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv

load_dotenv(_REPO_ROOT / ".env")

from flask import Flask, jsonify, request
from werkzeug.datastructures import FileStorage

from backend.core.config import Config, load_config
from backend.services.data_service import DataService, DataStoreCorrupted
from backend.services.ocr_service import OCRService

logger = logging.getLogger("ocr_service")

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}


def _file_size(file: FileStorage) -> int:
    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    return size


def validate_upload(file: FileStorage, config: Config) -> tuple[str, str | None]:
    """Return (extension, error). ``extension`` is '' when invalid."""
    extension = Path(file.filename or "").suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        return "", f"不支持的文件类型: {extension or '(未知)'}，允许 {', '.join(sorted(ALLOWED_EXTENSIONS))}"
    if _file_size(file) > config.max_upload_bytes:
        return "", f"文件超过大小限制 {config.max_upload_mb}MB"
    return extension, None


def configure_logging(config: Config) -> None:
    config.logs_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")
    handler = RotatingFileHandler(
        config.logs_dir / "ocr.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    root.addHandler(logging.StreamHandler(formatter))
    logging.getLogger("werkzeug").setLevel(logging.WARNING)


def create_app(config: Config | None = None) -> Flask:
    cfg = config or load_config()
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = cfg.max_upload_bytes + 1024 * 1024

    cors_origins = [o.strip() for o in cfg.cors_origins.split(",") if o.strip()]
    try:
        from flask_cors import CORS

        CORS(app, origins=cors_origins)
    except ImportError:
        logger.warning("flask-cors not installed; CORS disabled")

    ocr_service = OCRService(cfg)
    data_service = DataService(cfg)

    @app.route("/ocr/recognize", methods=["POST"])
    def recognize():
        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400
        file = request.files["file"]
        extension, error = validate_upload(file, cfg)
        if error:
            return jsonify({"error": error}), 400

        image_bytes = file.read()
        model = request.form.get("model", cfg.default_model)
        logger.info("Recognize request: %s (%s) %d bytes, model=%s",
                    file.filename, extension, len(image_bytes), model)
        try:
            results = asyncio.run(ocr_service.recognize_text(image_bytes, extension, model_name=model))
            return jsonify({"text": ocr_service.get_full_text(results), "details": results})
        except Exception:
            logger.exception("Recognize failed for %s", file.filename)
            return jsonify({"error": "OCR 服务内部错误，详情见日志 logs/ocr.log"}), 500

    @app.route("/ocr/save_label", methods=["POST"])
    def save_label():
        if "file" not in request.files or "text" not in request.form or "original_data" not in request.form:
            return jsonify({"error": "Missing file, text, or original_data"}), 400

        file = request.files["file"]
        extension, error = validate_upload(file, cfg)
        if error:
            return jsonify({"error": error}), 400

        text = request.form["text"]
        domain = request.form.get("domain", "general")
        try:
            original_data = json.loads(request.form["original_data"])
        except json.JSONDecodeError:
            return jsonify({"error": "original_data 不是合法的 JSON"}), 400
        if not isinstance(original_data, dict):
            return jsonify({"error": "original_data 必须是 JSON 对象"}), 400

        image_bytes = file.read()
        try:
            result = data_service.save_label(image_bytes, original_data, text, domain)
            return jsonify(result)
        except DataStoreCorrupted:
            logger.exception("Save label refused: store is corrupt")
            return jsonify({
                "error": "数据文件已损坏，本次保存已被拒绝以防覆盖历史数据。"
                         "请查看备份文件 *.corrupt-* 并人工恢复后重试。"
            }), 500
        except Exception:
            logger.exception("Save label failed")
            return jsonify({"error": "保存标注失败，详情见日志 logs/ocr.log"}), 500

    @app.route("/")
    def root():
        return jsonify({"message": "OCR System API (Flask) is running."})

    return app


def main() -> None:
    config = load_config()
    configure_logging(config)
    app = create_app(config)
    logger.info("Starting OCR service on %s:%s (CORS origins: %s)",
                config.host, config.port, config.cors_origins)
    app.run(host=config.host, port=config.port)


if __name__ == "__main__":
    main()
