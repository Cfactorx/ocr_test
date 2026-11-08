# BRD — 业务需求文档：ocr_test 项目问题诊断与整改

> 角色: 需求分析师 (RA) · 日期: 2026-11-04 · 状态: 已确认

## 1. 项目现状
ocr_test 是一个本地 OCR 工具：Flask 后端（图片/PDF → Ollama 视觉模型两段式识别，易错文本可用本地知识库/标注纠偏）+ 静态前端（拖拽上传、编辑、保存标注）+ JSON 文件存储（标注/知识库）+ EasyOCR 本地降级模型。

## 2. 痛点与业务目标
- 痛点：项目处于"能跑通 demo"状态，存在**数据丢失隐患、跨机器不可移植、无安全边界、无测试**四类风险，无法安全交付/迁移。
- 目标：消除 Critical 风险（数据安全、可移植性），收敛 High 风险（稳定性、安全暴露面、可维护性），为后续正式使用/部署铺平道路。

## 3. 问题清单（诊断结论）

### 🔴 Critical（必须整改）
| 编号 | 问题 | 证据 |
|------|------|------|
| C1 | **数据丢失**：`_load_labels`/`_load_kb` 在 JSON 损坏/异常时静默返回 `{}`，随后 `save_label` 会用 `{}` + 新记录**覆盖整个 labels.json / kb.json**，全部历史标注与知识库清零 | data_service.py:82,83,95,96 |
| C2 | **可移植性**：pdf2image 硬编码 `poppler_path=r"D:\poppler\Library\bin"`，换机器 PDF 功能直接失效；`data/`、`debug_ocr.log` 全部相对 CWD，`main.py` 只能从特定目录运行 | ocr_service.py:70, main.py:22 |
| C3 | **安全暴露面**：`CORS(app)` 无 origin 限制 + 开发服务器绑定 `0.0.0.0` 且无鉴权，局域网任何设备可直接上传文件并读写 `data/` 内文件内容 | main.py:15,80 |

### 🟠 High（应整改）
| 编号 | 问题 | 证据 |
|------|------|------|
| H1 | Flask 开发服务器用于"准生产"（Flask 自己警告 development server），且 `error.log` 内容证实以该模式运行 | main.py:80, error.log:1 |
| H2 | **事件循环阻塞**：async 端点内用 `asyncio.run` 再调同步 `requests.post`；EasyOCR `readtext`（重 CPU）在事件循环内同步执行；`asyncio.Semaphore(2)` 形同虚设（被阻塞调用架空） | main.py:43, ocr_service.py:137,74 |
| H3 | **零输入校验**：recognize 端点不限制文件类型/大小（任意文件字节都会进入 OCR 流程与知识库）；save_label 直接写 `file.read()` 进 labels 目录，无 MIME/大小校验 | main.py:25-53,56-73 |
| H4 | **双后端**：Flask (main.py) 与 FastAPI (api/recognize.py) 并存且契约不一致（FastAPI 无 model 参数、无 save_label、强制 image/*），维护两套实现、入口不明确 | api/recognize.py |
| H5 | **无测试、无 CI、无 lint**；全用 `print` 而非 logging（违反团队 Python 规范），`debug_ocr.log` 无滚动、无级别 | 全项目 |
| H6 | **依赖未锁版本**（numpy/easyocr 与 torch 组合极易漂移）；`__pycache__`、`data/`、日志文件均无 .gitignore 治理 | requirements.txt |

### 🟡 Medium（建议整改）
| 编号 | 问题 | 证据 |
|------|------|------|
| M1 | `confidence` 恒为 1.0/0.8 假值、`box` 恒空 → 前端"片段/坐标"能力名存实亡 | ocr_service.py:194-206 |
| M2 | 前端使用 `execCommand('copy')`（已弃用）、CDN 外链（Tailwind/flaticon，离线不可用）、alert 交互 | frontend/index.html |
| M3 | Ollama URL、模型名（默认 gemma4:31b-cloud）全部硬编码，无法用环境变量/配置覆盖 | ocr_service.py:15-16 |
| M4 | `migrate_kb.py` 静默吞异常 + CWD 相对路径，失败无告警 | scripts/migrate_kb.py:51 |
| M5 | 无 README/启动文档：Ollama 模型安装、poppler 安装、前后端启动步骤全靠口口相传 | — |
| M6 | 知识库纠偏提示取"最近 10 条纠错"纯时间序、与当前图片无关（非检索式），且每次识别全量扫描 labels.json | ocr_service.py:52 |

## 4. 业务边界
- 本轮**不做**：重写识别引擎、换向量检索 RAG、上数据库、上云部署。
- 整改目标是让现状代码**安全、可移植、可测试**，行为保持不变（P0 只修缺陷，不改交互）。

## 5. 验收底线
所有 Critical 项关闭 + 关键数据路径有自动化测试覆盖。
