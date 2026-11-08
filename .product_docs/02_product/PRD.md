# PRD — 产品需求文档：ocr_test 整改范围与验收标准

> 角色: 产品经理 (PM) · 日期: 2026-11-04 · 输入: BRD.md 问题清单

## 1. 整改分级（功能定义）

### P0 — 必须（对应 Critical + High 中数据安全/稳定项）
| 功能点 | 定义 | 验收标准 (AC) |
|--------|------|---------------|
| F1 数据安全 | `_load_*` 异常时**不得**返回空 dict 再覆盖；改为：损坏则抛 `DataStoreCorrupted`，保存前校验可解析，且写入走"读旧→合并→原子写（临时文件+rename）" | 单测：labels.json 写入 `{{{`（损坏）后调用 `save_label`，进程报错而非覆盖数据；正常合并写入后原子替换成功 |
| F2 可移植性 | poppler 路径、Ollama URL/模型、data 根目录全部走环境变量（`OCR_OLLAMA_URL`, `OCR_DEFAULT_MODEL`, `OCR_DATA_DIR`, `OCR_POPPLER_PATH`），提供 `.env.example`；代码内用 `pathlib` 以仓库根定位 data 目录 | 在不含 `D:\poppler` 的干净目录以 `python backend/main.py` 运行，图片识别可用；PDF 在设置 `OCR_POPPLER_PATH` 后可用 |
| F3 输入边界 | recognize/save_label 校验：MIME/扩展白名单（jpg/jpeg/png/webp/pdf）、单文件 ≤ 20MB、文件名净化（仅取扩展名） | 单测：上传 .exe/超 20MB → 400；正常 PDF → 正常流转 |
| F4 安全收敛 | CORS 白名单（默认 `http://localhost:5500,http://127.0.0.1:5500`，可用 env 覆盖）；默认 host `127.0.0.1`，env 可切 0.0.0.0；启动日志打印实际绑定 | 局域网无配置访问 → 无法连接或 CORS 拒绝 |
| F5 测试基线 | 新增 `tests/`（pytest）覆盖 DataService 合并/原子写/损坏防御 + OCRService 提示拼装 + 端点校验；覆盖率 ≥ 80%（services 层） | `pytest --cov` 通过且 services ≥ 80% |

### P1 — 应该（High 剩余 + Medium 中影响维护项）
| 功能点 | 定义 |
|--------|------|
| F6 阻塞治理 | Ollama 调用放线程池（`asyncio.to_thread`）；EasyOCR 推理放线程池；端点去掉 `asyncio.run` 反模式（Flask 同步端点直接 await 服务层 async 方法） |
| F7 单一后端 | 删除 FastAPI `api/recognize.py`（前端只调 Flask），消除双入口 |
| F8 日志治理 | `print` → `logging`（RotatingFileHandler，`logs/` 下滚动）；`migrate_kb.py` 报错非零退出 |
| F9 依赖治理 | `requirements.txt` 锁版本；新增 `.gitignore`（__pycache__/data/logs/*.log/.env） |

### P2 — 可以（Medium，随后续迭代）
F10 前端：`navigator.clipboard` 替换 execCommand；CDN 本地化可选；F11 置信度语义化（两段式标记 `refined: bool` 替代假 confidence）；F12 README 完整启动/部署文档（含 Ollama 模型与 poppler 安装）。

## 2. 非目标
不重写识别引擎、不上向量 RAG、不接数据库、不做鉴权体系（本地工具定位）、不改前端交互形态。

## 3. 用户路径（整改后不变，仅加防护）
上传图片 → 选模型 → 识别（两段式）→ 编辑 → 保存标注（纠偏入库 + 知识库合并）。
