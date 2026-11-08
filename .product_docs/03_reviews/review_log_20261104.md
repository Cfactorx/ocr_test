# 圆桌评审记录 — 2026-11-04 · ocr_test 整改方案

> 主持: 协调员 · 参会: RA / PM / TM / Dev / QA

## 议题与决议

### 1. F1 数据损坏处理策略（C1）
- **QA**：损坏后静默清库是最严重缺陷，必须用"损坏即拒绝写入 + 备份现有文件"防御；验收用例必须包含"损坏 JSON 不丢数据"。
- **TM**：同意。落地为三层：① `_load_*` 解析失败抛 `DataStoreCorrupted`（不再吞成 `{}`）；② `save_label` 捕获后先把原文件备份为 `.corrupt-YYYYMMDD` 再拒绝本次写入；③ 写入统一走 `write_json_atomic`（tmp + `os.replace`，同盘原子）。
- **Dev**：原子写用 `tempfile.NamedTemporaryFile(dir=同目录, delete=False)` + `os.replace`，Windows 同盘可原子替换。
- **决议**：✅ 按三层方案实施。AC 增加：损坏场景后原文件内容不变（被备份而非被覆盖）。

### 2. F2 路径与配置（C2）
- **RA**：data 目录定位以"仓库根"为锚（`Path(__file__).resolve().parents[1]` 即 `backend/` 的上级），`OCR_DATA_DIR` 可覆盖；避免 CWD 依赖。
- **TM**：poppler 缺失时 PDF 应报"未配置 OCR_POPPLER_PATH"的友好错误而非 pdf2image 的原始异常；图片路径不受影响。
- **决议**：✅ 全部配置走 `backend/core/config.py` 单点读取 env，默认值写死在 config 模块（Ollama URL 默认 `http://localhost:11434/api/generate`、模型默认 `gemma4:31b-cloud`）。

### 3. F4 安全默认值（C3）
- **QA**：本地工具定位下，默认 `127.0.0.1` + CORS 白名单是正确默认；需文档说明局域网共享时如何显式放开（`OCR_HOST=0.0.0.0` + `OCR_CORS_ORIGINS`）。
- **TM**：CORS 白名单无法阻止"服务端 0.0.0.0 暴露"本身，但能把浏览器侧攻击面收敛；启动时按实际配置打日志。
- **决议**：✅ 默认仅本机；放开必须显式 env。

### 4. F7 删除 FastAPI（H4）
- **Dev**：前端实际只调用 Flask 端点（`/ocr/recognize`, `/ocr/save_label`），FastAPI 文件从未被 main.py 挂载 → 可安全删除 `backend/api/`。
- **TM**：保留 `api` 包名留作未来 API 模块命名空间，或直接删干净。
- **决议**：✅ 删除 `backend/api/recognize.py`，保留 `api/__init__.py` 作为预留包（若后续无计划则整包删除，由 Dev 阶段定夺）。

### 5. F5 测试范围（H5）
- **QA**：services 层 80% 覆盖 + 端点校验 400 用例为最低线；Ollama 调用在测试中 monkeypatch，不依赖真实模型。
- **Dev**：EasyOCR 相关用例标记 `@pytest.mark.slow`，默认不跑（模型下载重）。
- **决议**：✅ 采用 pytest + monkeypatch；覆盖率门禁加在 services。

## 分歧闭环
| 分歧点 | 结论 |
|--------|------|
| 损坏数据"备份后拒绝" vs "备份后继续" | 拒绝写入（安全优先），备份保留现场供人工恢复 |
| CORS 默认值 | 显式白名单（非 `*`），env 可扩 |
| confidence 假值 | 本轮不动（P2 F11），避免改 API 契约 |

## 结论
全员 **AGREED**。PRD 已按共识更新（F1 加损坏备份条款、F2 加 config 单点、F4 加默认本机）。进入阶段 4（TDD）。
