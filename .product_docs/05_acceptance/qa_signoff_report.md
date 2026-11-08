# QA 测试报告 — ocr_test 整改（阶段 6）

> 角色: QA · 日期: 2026-11-08 · 测试框架: pytest 9.1.0（Python 3.14.0b3）

## 1. 执行结果
- 全量测试：**41 passed, 0 failed**（`python -m pytest tests/`；`pytest.ini` 中禁用了在 Python 3.14 下损坏的 langsmith 插件）
- 覆盖率（`--cov=backend.services`）：
  | 模块 | 覆盖率 |
  |------|--------|
  | data_service.py | 90% |
  | ocr_client.py | 100% |
  | ocr_service.py | 80% |
  | **合计** | **85%（门禁 ≥80% ✅）** |

## 2. AC 验证对照（PRD P0）
| AC | 验证方式 | 结果 |
|----|----------|------|
| F1 损坏 JSON 不覆盖 | `test_corrupt_labels_refuses_write_and_preserves_data`：写入 `{not json!!` 后 save_label 抛 `DataStoreCorrupted`，原文件内容不变，生成 `.corrupt-*` 备份 | ✅ |
| F2 可移植性 | config 路径锚定仓库根（`test_data_dir_anchored_to_repo_root_by_default`）；poppler 经 env 传入；无 `D:\poppler` 时 PDF 报友好错误（`test_pdf_without_poppler_config_raises_friendly_error`） | ✅ |
| F3 输入边界 | `.exe` → 400、超限 → 400（`test_recognize_rejects_*`） | ✅ |
| F4 安全收敛 | 默认 host 127.0.0.1 + CORS 白名单（`test_defaults`）；局域网放开需显式 env | ✅ |
| F5 测试基线 | 41 用例全绿，services 覆盖率 85% | ✅ |

## 3. P1 验证
- F6 阻塞治理：Ollama/EasyOCR 全部经 `asyncio.to_thread`；`test_easyocr_inference_runs_via_thread` 验证线程化 ✅
- F7 双后端：`backend/api/` 已删除，grep 确认无残留引用 ✅
- F8 日志：`logs/ocr.log` 滚动 5MB×3；migrate 脚本失败 exit 1 ✅
- F9 依赖：requirements 锁版本（Flask 3.1.3 等 9 项 + pytest/pytest-cov）；.gitignore 排除 data/logs/.env/__pycache__ ✅

## 4. Bug 清单（本轮开发中发现并修复）
| Bug | 修复 | 回归测试 |
|-----|------|----------|
| `original_data` 非 JSON 时 500 | 400 + 明确错误 | `test_save_label_rejects_bad_original_data` |
| oversize 用例被 Flask MAX_CONTENT_LENGTH 抢先 413 | MAX_CONTENT_LENGTH = 上限+1MB，端点层校验生效 | `test_recognize_rejects_oversized_upload` |

## 5. QA Sign-off
**通过（PASS）。** P0/P1 验收标准全部达成，无遗留阻塞缺陷。已知边界：
- OCR 真实识别依赖本机 Ollama（`gemma4:31b-cloud`），端到端识别未在本机 QA 中执行（需 GPU/模型就绪）；HTTP 契约已用 mock 全量覆盖。
- PDF 功能需 `OCR_POPPLER_PATH` 指向本机 poppler 后方可用。
