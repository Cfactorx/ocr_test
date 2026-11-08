# TDD — 技术设计文档：ocr_test 整改实施设计

> 角色: 技术经理 (TM) · 日期: 2026-11-04 · 输入: PRD.md (P0/P1) + 评审决议

## 1. 目标架构（整改后，行为不变原则）
```
backend/
├── main.py                 # Flask 应用工厂 + 端点（同步端点内 await 服务层）
├── core/config.py          # ★ 新增：env 配置单点（dataclass 冻结）
├── services/
│   ├── ocr_service.py      # 改：读 config；Ollama/EasyOCR 走 to_thread
│   ├── data_service.py     # 改：原子写 + 损坏防御 + 备份
│   └── ocr_client.py       # ★ 新增：Ollama HTTP 客户端（可被 monkeypatch）
├── api/recognize.py        # 删（FastAPI 死代码）
└── scripts/migrate_kb.py   # 改：失败 sys.exit(1) + 日志
frontend/index.html         # P2 F10 才动，本轮不改
tests/                      # ★ 新增：pytest
```

## 2. 模块设计

### 2.1 core/config.py（新增）
```python
@dataclass(frozen=True)
class Config:
    ollama_url: str
    default_model: str
    data_dir: Path          # 默认 repo 根/data，OCR_DATA_DIR 可覆盖
    labels_dir: Path        # data_dir/labels
    kb_dir: Path            # data_dir/knowledge_base
    poppler_path: str | None   # OCR_POPPLER_PATH，None 时自动探测
    cors_origins: str       # 逗号分隔，默认 localhost:5500/127.0.0.1:5500
    host: str               # 默认 127.0.0.1
    port: int               # 默认 8080
    max_upload_mb: int      # 默认 20

def load_config() -> Config: ...   # 读 env + 计算路径锚点
```
- 路径锚点：`Path(__file__).resolve().parents[1].parent`（仓库根），再拼 `data/`。
- 全部字段有默认值 → 零配置可跑图片识别；PDF 需 `OCR_POPPLER_PATH`。

### 2.2 data_service.py（改造，关键不变式）
- 新增 `class DataStoreCorrupted(Exception)`。
- `_load_json(path)`：文件不存在→`{}`；**解析失败→抛 `DataStoreCorrupted`**（不再吞成 `{}`）。
- 新增 `write_json_atomic(path, obj)`：`NamedTemporaryFile(dir=path.parent, delete=False)` → `json.dump` → `f.close()` → `os.replace(tmp, path)`。
- `save_label(...)` 流程：
  1. 读旧 labels/kb（可能抛 Corrupted）；
  2. `except DataStoreCorrupted: 备份原文件为 <name>.corrupt-YYYYMMDDHHMMSS 并 re-raise`（拒绝写入，保留现场）；
  3. 合并旧数据 + 新记录 → `write_json_atomic`。
- 图片落盘保持原逻辑（文件名时间戳），但扩展名白名单由端点先行校验。

### 2.3 ocr_client.py（新增）
```python
class OllamaClient:
    def __init__(self, url: str, timeout: int = 120): ...
    def generate(self, model: str, prompt: str, image_b64: str) -> str:
        # requests.post + raise_for_status；返回 response 文本
```
- 好处：HTTP 细节隔离，测试 monkeypatch 该客户端即可；阻塞调用集中于此。

### 2.4 ocr_service.py（改造）
- 构造改注入 `Config`（默认 `load_config()`）。
- `_process_image_ocr`：Ollama 两段调用 → `await asyncio.to_thread(client.generate, ...)`；EasyOCR `readtext` → `await asyncio.to_thread(reader.readtext, ...)`。
- PDF：`convert_from_bytes(file_bytes, dpi=200, poppler_path=config.poppler_path)`；`poppler_path` 为空且 poppler 不在 PATH → 友好异常"请设置 OCR_POPPLER_PATH"。
- Semaphore(2) 保留，配合 to_thread 后并发语义才真正生效。

### 2.5 main.py（改造）
- 应用工厂 `create_app(config=None)`，注入配置便于测试。
- 端点改同步 `def`，内部 `asyncio.run(ocr_service.recognize_text(...))` 保留（Flask 同步端点内跑事件循环是安全的单例用法）——H2 的"嵌套事件循环"风险实际不成立，真正的阻塞点在 to_thread 化后消除。
- 输入校验工具 `validate_upload(file, config) -> (extension, error)`：扩展白名单 + `file.seek(0,2)` 取大小 ≤ max_upload_mb。
- `CORS(app, origins=config.cors_origins)`；`app.run(host=config.host, port=config.port)`；启动日志打印绑定地址。
- 删除 `write_debug_log` 临时文件 hack，统一 `logging`（F8：`RotatingFileHandler`，`logs/ocr.log`，5MB×3）。

## 3. 数据 Schema（不变，仅加防御）
- `labels.json`: `{ "<img_*.jpg>": { metadata: {timestamp, domain, is_corrected}, ocr_details: {original_text, original_fragments[], corrected_text}, tags[] } }`
- `kb.json`: `{ "<img_*.jpg>": { text, domain, timestamp, source_image } }`

## 4. 测试设计（F5）
| 文件 | 用例要点 |
|------|----------|
| tests/test_data_service.py | 损坏 JSON 不覆盖（备份+抛错）、正常合并、原子写（tmp 清理）、目录自动创建 |
| tests/test_ocr_service.py | monkeypatch OllamaClient：两段式拼装 prompt、refine 失败回退 initial、corruption hints 截取 10 条 |
| tests/test_api.py | Flask test_client：无 file 400、.exe 400、超大小 400、正常 200（mock service） |
| tests/test_config.py | env 覆盖、路径锚点、默认值 |
- 覆盖率门禁：`pytest --cov=backend.services` ≥ 80%。
- EasyOCR 用例 `@pytest.mark.slow` 默认 deselect。

## 5. 实施顺序（阶段 5 执行计划）
1. `core/config.py` + tests/test_config.py（地基）
2. `data_service` 原子写/损坏防御 + 测试（先修 C1，风险最高）
3. `ocr_client` 抽离 + `ocr_service` to_thread + 测试
4. `main.py` 校验/CORS/host + 测试
5. 删 `api/recognize.py`、F8 日志、F9 .gitignore + 锁版本
6. 全量 `pytest --cov` 绿 → 交付 QA

## 6. 风险预判
| 风险 | 缓解 |
|------|------|
| Windows `os.replace` 目标被占用（服务运行时覆盖） | 测试在关闭服务后进行；文档说明 |
| 删除 FastAPI 后有人依赖 `/api/recognize` | grep 确认前端仅调 `/ocr/*`（已核实） |
| Ollama 模型名默认值与现网一致 | 默认值照搬现值 `gemma4:31b-cloud`，仅加 env 覆盖 |
