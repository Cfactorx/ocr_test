"""Tests for backend.core.config."""

from backend.core.config import Config, load_config


def test_defaults():
    cfg = load_config(env={})
    assert cfg.ollama_url == "http://localhost:11434/api/generate"
    assert cfg.default_model == "gemma4:31b-cloud"
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 8080
    assert cfg.max_upload_mb == 20
    assert cfg.poppler_path is None
    assert "127.0.0.1:5500" in cfg.cors_origins


def test_data_dir_anchored_to_repo_root_by_default():
    cfg = load_config(env={})
    assert cfg.data_dir.parts[:1]  # non-empty absolute-ish path
    assert cfg.data_dir.name == "data"
    assert cfg.labels_dir == cfg.data_dir / "labels"
    assert cfg.kb_file == cfg.data_dir / "knowledge_base" / "kb.json"


def test_env_overrides(tmp_path):
    cfg = load_config(
        env={
            "OCR_OLLAMA_URL": "http://gpu:11434/api/generate",
            "OCR_DEFAULT_MODEL": "llava",
            "OCR_DATA_DIR": str(tmp_path / "mydata"),
            "OCR_POPPLER_PATH": r"C:\poppler\bin",
            "OCR_HOST": "0.0.0.0",
            "OCR_PORT": "9000",
            "OCR_MAX_UPLOAD_MB": "50",
            "OCR_CORS_ORIGINS": "https://example.com",
        }
    )
    assert cfg.ollama_url == "http://gpu:11434/api/generate"
    assert cfg.default_model == "llava"
    assert cfg.data_dir == tmp_path / "mydata"
    assert cfg.poppler_path == r"C:\poppler\bin"
    assert cfg.host == "0.0.0.0"
    assert cfg.port == 9000
    assert cfg.max_upload_bytes == 50 * 1024 * 1024
    assert cfg.cors_origins == "https://example.com"


def test_config_is_frozen():
    cfg = Config()
    try:
        cfg.host = "0.0.0.0"
    except AttributeError:
        return
    raise AssertionError("Config should be frozen (immutable)")


def test_empty_poppler_env_yields_none():
    cfg = load_config(env={"OCR_POPPLER_PATH": ""})
    assert cfg.poppler_path is None


def test_invalid_port_env_raises_clear_error():
    import pytest

    with pytest.raises(ValueError, match="OCR_PORT"):
        load_config(env={"OCR_PORT": "not-a-number"})


def test_non_positive_max_upload_raises():
    import pytest

    with pytest.raises(ValueError, match="OCR_MAX_UPLOAD_MB"):
        load_config(env={"OCR_MAX_UPLOAD_MB": "0"})
