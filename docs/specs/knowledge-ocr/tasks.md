# Tasks: 知识库图片与扫描 PDF OCR（P0-2）

## T1 配置与依赖

- [x] T1.1 `apps/api/src/ticket_agent/shared/settings.py` 新增 7 个 `knowledge_ocr_*` 字段与 `inherit_knowledge_ocr_credentials` validator。
- [x] T1.2 `apps/api/pyproject.toml` 增加 `pypdfium2>=4.30,<6`、`pillow>=10,<13`（初版曾用 pymupdf，因 AGPL 许可在 T8 替换）。
- [x] T1.3 `cd apps/api && uv lock` 更新 `apps/api/uv.lock`。
- [x] T1.4 `.env.example` 新增 OCR 配置块。

## T2 OCR provider

- [x] T2.1 新增 `apps/api/src/ticket_agent/knowledge/ocr.py`：`OCRUnavailableError`、`OCRResult`、`OCRProvider`、`DashScopeChatOCR`、`get_ocr_provider`。
- [x] T2.2 新增 `apps/api/tests/unit/test_knowledge_ocr.py`，覆盖请求协议、响应解析、错误路径、provider=none。

## T3 解析与页码

- [x] T3.1 `document_parser.py`：`TextBlock` 增加 page/ocr，`BlockKind` 增加 image_text，`serialize_blocks` 条件输出。
- [x] T3.2 `parse_document` 支持图片后缀并在未配置 OCR 时返回 `OCR_NOT_CONFIGURED`。
- [x] T3.3 PDF 改为逐页：pypdf 路径写页码；启用 OCR 时用 pypdfium2 渲染低文字页并 OCR。
- [x] T3.4 `chunking.py`：`ChunkDraft` 增加 page_start/page_end，分块时保留页码。
- [x] T3.5 `service.py`：持有 OCR provider 并传给两处 `parse_document`；`_write_chunks` 写 page_start/page_end。

## T4 检索透传

- [x] T4.1 `RetrievalCandidate`/`KnowledgeHit` 增加 page 字段，`_retrieval_candidate` 与 `search` 透传。
- [x] T4.2 `knowledge/schemas.py` `KnowledgeHitView` 增加可选 page 字段，router 赋值透传。
- [x] T4.3 `customer_service/suggestions.py` `_citation_payload` 输出 page 字段。

## T5 测试

- [x] T5.1 扩展 `tests/unit/test_document_parser.py`：图片 OCR、未配置拒绝、OCR 失败、文字 PDF 页码、混合 PDF、扫描 PDF 无 OCR。
- [x] T5.2 扩展 `tests/unit/test_knowledge_chunking.py`：跨页 chunk、表格/拆分页码继承、旧数据无页码。
- [x] T5.3 扩展 `tests/integration/knowledge/test_knowledge_flow.py`：两页 PDF 的 chunk metadata 页码；假 provider 图片上传链路。

## T6 验收

- [x] T6.1 专项 pytest：单测 38 passed，knowledge 集成 29 passed。
- [x] T6.2 全量 `uv run pytest -q`：**693 passed**（配置 `TEST_POSTGRES_URL` 后 PostgreSQL 专项 2 项也执行，无 skip）。
- [x] T6.3 `uv run ruff check src tests`：All checks passed。
- [x] T6.4 `uv run mypy src`：208 files，no issues。
- [x] T6.5 真实 PostgreSQL 验收：Docker 启动 `pgvector/pgvector:pg16`（PostgreSQL 16.15，pgvector 0.8.7），`alembic upgrade head` 落在 `e1a7c4d90b62`，`migration_preflight --expect-head` 返回 `at_head`；真实 OCR 上传 201、chunk 页码 1/1；`scripts/smoke_closed_loop.py` 在 PostgreSQL 上通过。
- [x] T6.6 全栈 Smoke 与 `pnpm --dir apps/web build`：uvicorn + `scripts/smoke_closed_loop.py` 通过；tsc 与 Vite build 通过。
- [x] T6.7 真实图片/扫描 PDF 上传：本机 `.env` 的 `KNOWLEDGE_OCR_*`（复用 DashScope 密钥，`qwen-vl-ocr`）真实调用通过；在真实 PostgreSQL 上经 HTTP 上传扫描 PDF，201，chunk `page_start=1/page_end=1`（验收时 parser 为 `pymupdf+dashscope`，T8 后变更为 `pdfium+dashscope`）。

## T7 文档

- [x] T7.1 更新 `outputs/07_开发日志.md`。
- [x] T7.2 更新 `outputs/06_当前实施状态.md`。
- [x] T7.3 更新 `README.md` 知识库格式与 OCR 配置说明。

## T8 许可整改（PyMuPDF AGPL → pypdfium2）

- [x] T8.1 `document_parser.py`：`_parse_pdf_with_pymupdf` 重写为 `_parse_pdf_with_pdfium`，渲染 `page.render(scale=200/72).to_pil()` → PNG；`parser_name` 改为 `pdfium[+provider]`。
- [x] T8.2 测试改用 reportlab（BSD）构造 PDF；`pymupdf+fake` 断言改为 `pdfium+fake`。
- [x] T8.3 依赖：移除 pymupdf，新增 pypdfium2 5.14.0 / pillow 12.3.0 / reportlab 5.1.0（dev）；`uv lock` 同步。

## 完成定义

- 所有 T1-T7 完成，或明确记录未完成原因。
- 最终回复列出正常路径、异常路径、真实/临时验收数据、未验收外部依赖、剩余风险。
- 不执行 git commit（用户明确要求先不提交）。
