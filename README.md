# OCR 文字识别系统

Flask + Ollama 的两段式 OCR 系统：上传图片 / PDF → 视觉模型初识 + LLM 精修 → 可编辑结果 → 保存标注（纠错入库 + 知识库合并）。

```
backend/    Flask 服务（/ocr/recognize、/ocr/save_label）
frontend/   纯静态单页（frontend/index.html，任意静态服务器打开）
tests/      pytest 测试基线
data/       标注与知识库（labels.json / kb.json，运行时生成）
```

## 前置要求

- Python 3.10+
- [Ollama](https://ollama.com)（本地模型推理服务）
- 处理 PDF 时另需 [poppler](https://poppler.freedesktop.org/)（见下文）

## 1. 安装依赖

```bash
cd ocr_test
python -m venv .venv            # 可选：使用虚拟环境
# Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt
```

`backend/requirements.txt` 已锁定全部版本（Flask、pdf2image、Pillow、easyocr 等），直接安装即可。

## 2. 安装 Ollama 模型

默认使用 `gemma4:31b-cloud`。安装 Ollama 并启动后，拉取模型：

```bash
ollama pull gemma4:31b-cloud
```

前端下拉框还列出了 `llama3.2-vision`、`llava`、`bakllava` 等可选模型（需另行 `ollama pull`），以及本地传统 OCR 引擎 `easyocr`（无需 Ollama，但首次使用会自动下载 EasyOCR 模型，需联网）。

## 3. 安装 poppler（仅 PDF 输入需要）

`pdf2image` 底层依赖 poppler 的 `pdftoppm` 二进制。

- **Windows**：下载 [poppler-windows](https://github.com/oschwartz10612/poppler-windows)（或 MSYS2 包 `msys2-devel` 下的 poppler），解压到例如 `D:\poppler`，可执行文件在 `D:\poppler\Library\bin`。
- **Linux (Debian/Ubuntu)**：`sudo apt install poppler-utils`（默认路径通常无需配置）。
- **macOS**：`brew install poppler`（默认路径通常无需配置）。

非默认安装位置时，需通过环境变量 `OCR_POPPLER_PATH` 指向 poppler 可执行文件所在目录（Windows 即 `...\Library\bin`）。图片识别不需要 poppler。

## 4. 配置（可选）

所有配置项均可用环境变量覆盖，模板见 [.env.example](.env.example)：

```bash
cp .env.example .env   # 按需修改后保存；不修改则全部用默认值
```

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OCR_OLLAMA_URL` | `http://localhost:11434/api/generate` | Ollama 推理端点 |
| `OCR_DEFAULT_MODEL` | `gemma4:31b-cloud` | 默认视觉模型 |
| `OCR_DATA_DIR` | `<仓库根>/data` | 标注/知识库目录 |
| `OCR_LOG_DIR` | `<仓库根>/logs` | 日志目录 |
| `OCR_POPPLER_PATH` | 无（走系统 PATH） | poppler 可执行文件目录，PDF 输入必填（非默认位置时） |
| `OCR_HOST` | `127.0.0.1` | 监听地址；局域网共享需设 `0.0.0.0` 并配合下一项 |
| `OCR_CORS_ORIGINS` | `http://localhost:5500,http://127.0.0.1:5500` | 允许的前端来源白名单 |
| `OCR_PORT` | `8080` | 服务端口 |
| `OCR_MAX_UPLOAD_MB` | `20` | 单文件上传上限（MB） |

> 服务只读取**进程环境变量**；`backend/main.py` 会加载仓库根的 `.env` 文件（python-dotenv）。

## 5. 启动服务

**后端**（在仓库根目录执行）：

```bash
python backend/main.py
```

启动后监听 `http://127.0.0.1:8080`（端口/地址以 `OCR_HOST`/`OCR_PORT` 为准），日志输出到终端与 `logs/ocr.log`。

**前端**：`frontend/index.html` 是纯静态页，用任意静态服务器打开即可，例如 VS Code Live Server（默认端口 5500）：

```bash
npx serve frontend        # 或 python -m http.server 5500 -d frontend
```

- Live Server / `python -m http.server`：浏览器访问 `http://localhost:5500`（端口任意，需在 CORS 白名单内，见上表）。
- 前端已硬编码调用后端 `http://localhost:8080`，后端地址变化时需同步改 `frontend/index.html` 中的 URL。
- 页面流程：拖入图片/PDF → 选模型 → 「开始识别文字」→ 编辑结果 → 「保存标注」入库。

## 6. 运行测试

```bash
python -m pytest tests/
```

需要 41 个用例全绿。带覆盖率：

```bash
python -m pytest tests/ --cov=backend --cov-report=term-missing
```

## 故障排查

| 现象 | 处理 |
|------|------|
| 识别失败：Ollama 连接错误 | 确认 Ollama 已启动、`OCR_OLLAMA_URL` 可达（`curl http://localhost:11434/api/tags`） |
| PDF 转图失败 | 安装 poppler 并设 `OCR_POPPLER_PATH`（见第 3 节） |
| 浏览器报错 CORS | 前端实际运行端口不在 `OCR_CORS_ORIGINS` 白名单内 |
| 保存标注报「数据文件已损坏」 | `data/**/labels.json` 或 `kb.json` 不可解析，进程会保留 `*.corrupt-*` 备份并拒绝写入，请人工核对备份后恢复 |
| 日志位置 | `logs/ocr.log`（滚动，保留 3 份） |
