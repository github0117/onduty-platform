# Spec: 知识库图片与扫描 PDF OCR（P0-2）

## 1. 目标与范围

让知识库上传支持图片与扫描版 PDF，并把页码保留到 chunk metadata 与检索命中，供引用展示。

范围内：

- 图片：`.png/.jpg/.jpeg/.webp/.bmp/.tif/.tiff`，经 OCR 转单页文本块。
- PDF：混合页文档逐页判断；有文字页直接取文本，无文字/低文字页渲染后 OCR。
- 页码：block 携带页码；chunk metadata 记录 `page_start/page_end`；检索命中透传页码。
- 配置：新增 `KNOWLEDGE_OCR_*`，默认 `none` 保持旧行为。
- 测试：不调用真实 DashScope，使用注入的 httpx Client/假 provider。

不在范围内：

- docx 内嵌图片 OCR。
- PDF 表格结构还原。
- 消息/工单附件 OCR。
- 外部连接器文档 OCR。
- 前端新增页码展示组件（仅透传字段，避免本轮扩大前端改动）。

## 2. 配置设计

在 [settings.py](file:///Users/song/Documents/Codex/2026-10-23/mvp-hr-1-2-sop-rag/apps/api/src/ticket_agent/shared/settings.py) 的 knowledge 配置段新增：

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `knowledge_ocr_provider` | `"none"` | `none` 或 `dashscope` |
| `knowledge_ocr_base_url` | `""` | OpenAI 兼容端点；为空回退 `model_base_url` |
| `knowledge_ocr_api_key` | `""` | 为空回退 `model_api_key` |
| `knowledge_ocr_model_name` | `""` | 为空回退 `model_name` |
| `knowledge_ocr_timeout_seconds` | `60.0` | 单次请求超时 |
| `knowledge_ocr_max_pages` | `50` | 最多 OCR 的页数；超出页仍用原生文本 |
| `knowledge_ocr_min_text_chars` | `30` | 页面原生文本低于该长度才 OCR |

新增 `model_validator`，仅当 `knowledge_ocr_provider == "dashscope"` 时回填 base/key/model；不回填任何字面密钥。
`knowledge_ocr_provider == "dashscope"` 但最终 base/model 为空时，`DashScopeChatOCR` 抛 `OCRUnavailableError`，解析层转 `OCR_NOT_CONFIGURED` 明确报错，不静默降级。

同步更新 `.env.example`，并注明“未配置专用密钥时复用 MODEL_*；密钥只从本机 .env 注入”。

## 3. 新增 `knowledge/ocr.py`

```python
class OCRUnavailableError(Exception): ...

@dataclass(frozen=True)
class OCRResult:
    text: str
    provider: str
    model_name: str

class OCRProvider(Protocol):
    name: str
    def extract_text(self, *, data: bytes, content_type: str) -> OCRResult: ...

class DashScopeChatOCR:
    name = "dashscope"
    def __init__(self, settings: Settings, *, client: httpx.Client | None = None) -> None: ...
    def extract_text(self, *, data: bytes, content_type: str) -> OCRResult: ...

def get_ocr_provider(settings: Settings | None = None) -> OCRProvider | None: ...
```

实现细节：

- 端点：`f"{base_url.rstrip('/')}/chat/completions"`。
- 请求体：`temperature=0`，一条 user message，内容为 `image_url` data URI + 文本提示“提取图片中所有实际可见文字，保持阅读顺序，只返回文字；没有文字时返回空”。
- 响应：取 `choices[0].message.content`；兼容字符串和 `[{type: text, text: ...}]` 列表；`"" / "0" / "无" / "无文字"` 归一为空串。
- 非 `image/*`、非 2xx、响应缺 content、base/model 缺失 → `OCRUnavailableError`。
- 不做文本脱敏（图片不含文本输入）；`httpx.Client` 可注入以便测试。

## 4. `document_parser.py` 改动

### 4.1 数据模型

- `BlockKind` 增加 `"image_text"`。
- `TextBlock` 增加 `page: int | None = None`、`ocr: bool = False`（保持 frozen 与旧调用兼容）。
- `parse_document(..., ocr_provider: OCRProvider | None = None)`；现有调用不传时行为不变。
- `serialize_blocks` 在 block 有页码/OCR 时输出 `"page"`、`"ocr"`，否则不输出，保持旧 JSON 兼容。

### 4.2 图片

- 新常量 `_IMAGE_SUFFIXES`。
- `_parse_image(data, filename, content_type, ocr_provider)`：
  - provider 为 None → `DocumentParseError("OCR_NOT_CONFIGURED", "Image documents require OCR; configure KNOWLEDGE_OCR_PROVIDER.")`。
  - 按后缀推断 media type（content_type 非 `image/*` 时使用后缀映射）。
  - 调 `provider.extract_text`；`OCRUnavailableError` → `DocumentParseError("OCR_FAILED", ...)`。
  - 文本为空 → `EMPTY_DOCUMENT`。
  - 单块：`TextBlock(kind="image_text", text=..., page=1, ocr=True)`；`parser_name = f"{provider.name}-ocr"`。

### 4.3 PDF

新增 `_parse_pdf_document(data, ocr_provider)`：

- `ocr_provider is None`：走 `_parse_pdf_pages_pypdf`，复用 pypdf 逐页 `extract_text()`，页码写入 blocks。
- `ocr_provider is not None`：走 `_parse_pdf_with_pymupdf`：
  - `import pymupdf` 失败 → `PDF_PARSER_UNAVAILABLE`。
  - `page.get_text("text")`；`len(text.strip()) >= min_text_chars` 直接使用，`ocr=False`。
  - 否则当页 OCR 次数未超过 `knowledge_ocr_max_pages` 时 `page.get_pixmap(dpi=200, colorspace=pymupdf.csRGB, alpha=False).tobytes("png")` → provider OCR，`ocr=True`。
  - 单页 `OCRUnavailableError` 回退原生文本并记录 warning `"OCR_FAILED"`；若整篇无可用文本，抛 `OCR_FAILED`（有原生文本则保留）。
  - `parser_name="pymupdf"`；有 OCR 页时 `"pymupdf+<provider>"`。
- 共用 `_page_blocks_from_texts(pages, ocr_pages)`：
  - `normalize_whitespace` 后，页数 ≥3 时用 `strip_repeated_page_artifacts` 去页眉页脚。
  - 每页 `clean_text(page, merge_wrapped=True)` 后 `_paragraph_blocks`，逐块写 `page=1-based` 与 `ocr`。
  - warnings 聚合 `quality_warnings("\n\n".join(page_texts))`，去重。
- 旧行为兼容：纯扫描 PDF 且 OCR 未启用仍报 `EMPTY_DOCUMENT`（现有单测保持通过）。

## 5. `chunking.py` 改动

- `ChunkDraft` 增加 `page_start: int | None = None`、`page_end: int | None = None`。
- `chunk_blocks` 内部保留 block 的 `page`。
- `_pack_section`：
  - table 原子块沿用其 page。
  - 超长段拆分为多块时每块继承原 block page。
  - buffer flush 时用 `_page_range(buffer)` 计算 min/max，忽略 None。
- `_draft(..., page_start, page_end)`。

## 6. 页码贯穿检索

- `service.py` `RetrievalCandidate` 增加 `page_start/page_end`；`_retrieval_candidate` 从 `chunk.metadata_json` 读取。
- `_write_chunks` 在 draft 有页码时写 `metadata["page_start"]`、`metadata["page_end"]`。
- `KnowledgeHit` 增加 `page_start/page_end`；`search` 透传。
- `KnowledgeHitView` 增加可选字段（`schemas.py`）。
- `customer_service/suggestions.py` `_citation_payload` 增加 `page_start/page_end`（None 也输出，保持结构稳定）。
- `KnowledgeService.__init__` 持有 `self.ocr_provider = get_ocr_provider(self.settings)`；`create_version_from_file` 与 `ingest_stored_version` 调 `parse_document` 时传入。

## 7. 依赖

- `apps/api/pyproject.toml` 增加 `pymupdf>=1.24,<2`。
- mypy override 增加 `pymupdf` 的 `ignore_missing_imports`。
- 执行 `cd apps/api && uv lock` 更新 `uv.lock`。
- 已知风险：PyMuPDF 为 AGPL 许可。上线分发前需替换为 `pypdfium2`/商业许可；本轮先在内部环境使用并在开发日志标注。

## 8. 测试矩阵

单元：

1. `tests/unit/test_knowledge_ocr.py`
   - provider=none → `get_ocr_provider` 返回 None。
   - httpx `MockTransport` 校验请求路径、Authorization、data URI、提示词。
   - 响应字符串/列表/空标记解析。
   - 非 2xx、缺 content、缺 base/model → `OCRUnavailableError`。
2. `tests/unit/test_document_parser.py` 增补
   - 图片 + 假 provider → 单块 `image_text`、`page=1`、`ocr=True`。
   - 图片无 provider → `OCR_NOT_CONFIGURED`。
   - provider 抛错 → `OCR_FAILED`。
   - pypdf 多页文字 PDF → block 页码 1/2。
   - pymupdf 混合 PDF：第 1 页文字、第 2 页图片（无文字）→ 第 2 页 OCR，block `ocr=True`、`page=2`。
   - 纯扫描 PDF 无 OCR → `EMPTY_DOCUMENT`。
3. `tests/unit/test_knowledge_chunking.py` 增补
   - 跨页段落 chunk 的 `page_start/page_end`。
   - 表格/超长段拆分后的页码继承。
   - 无 page 的旧 blocks 仍返回 None。

集成（SQLite 测试库、真实 ORM 链路）：

4. `tests/integration/knowledge/test_knowledge_flow.py`
   - 上传两页文字 PDF → `KnowledgeChunk.metadata_json` 含正确 `page_start/page_end`，`chunking_version=v2`。
   - 检索或直接构造 `KnowledgeHitView` 断言页码字段可序列化。
   - 通过 monkeypatch `ticket_agent.knowledge.service.get_ocr_provider` 注入假 provider，上传 PNG → version 完成、block 为 `image_text`、chunk metadata 含 `page_start=1`。

## 9. 验收命令与真实环境

```bash
cd apps/api
uv lock
uv run pytest tests/unit/test_knowledge_ocr.py tests/unit/test_document_parser.py tests/unit/test_knowledge_chunking.py -q
uv run pytest tests/integration/knowledge/test_knowledge_flow.py -q
uv run pytest -q
uv run ruff check src tests
uv run mypy src
```

全栈：

```bash
uv run alembic upgrade head        # 真实 PostgreSQL，无新迁移，检查 head 不变
make smoke                         # 或仓库既有全栈 Smoke 命令
pnpm --dir apps/web build          # 前端无改动，仍执行生产构建
```

外部依赖未验收声明：

- 不调用真实 DashScope OCR（无生产密钥），仅用注入 client/假 provider 验证协议与链路。
- 若本机 `.env` 未配置 `KNOWLEDGE_OCR_*`，真实图片/扫描 PDF 上传会明确返回 `OCR_NOT_CONFIGURED`，这是预期行为。

## 10. 文档更新

- `outputs/07_开发日志.md`：记录实现、测试结果、未验收项、PyMuPDF 许可风险。
- `outputs/06_当前实施状态.md`：把 P0-2 状态更新为已完成/待外部验收。
- `.env.example`：新增 OCR 配置块。
- `README.md`：知识库支持格式与 OCR 配置一节。

## 11. 风险与回滚

- PyMuPDF AGPL 许可风险（见 §7）。
- OCR 成本与延迟随页数增长：通过 `MAX_PAGES`、`MIN_TEXT_CHARS` 控制。
- 低质量扫描件 OCR 结果可能含噪声：保留 `ocr=True` 标记与 `OCR_FAILED` warning，便于后续质量治理。
- 回滚：设 `KNOWLEDGE_OCR_PROVIDER=none` 即恢复旧行为；已入库 chunk 的 `page_*` 字段对旧检索无破坏。
