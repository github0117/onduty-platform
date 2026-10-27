import json
from uuid import uuid4

from ticket_agent.customer_service.suggestions import (
    _deepwiki_contents_summary,
    _is_technical_documentation_question,
    _operational_knowledge_draft,
    _repository_name,
    _resolved_repository,
    _security_boundary_refusal,
    _technical_documentation_draft,
    _technical_documentation_plan,
    _technical_evidence_missing_draft,
    _technical_knowledge_draft,
)
from ticket_agent.knowledge.service import KnowledgeHit
from ticket_agent.mcp_connectors.runtime import (
    McpExecutionResult,
    McpToolTarget,
)
from ticket_agent.model_gateway.types import ToolPlan
from ticket_agent.tickets.drafts import DraftEvidence
from ticket_agent.tickets.models import Ticket


def test_repository_name_extraction() -> None:
    assert (
        _repository_name(
            "请查询 modelcontextprotocol/python-sdk 的文档结构"
        )
        == "modelcontextprotocol/python-sdk"
    )
    assert _repository_name("请查询公开仓库文档") is None
    assert _repository_name("请提供 owner/repo 格式的仓库") is None
    assert _is_technical_documentation_question("查询公开仓库文档的安全限制")
    assert (
        _resolved_repository(
            "买家：https://github.com/huangjia2019/rag-in-action "
            "这个地址项目是什么内容\n"
            "买家：你帮我查询一下这个仓库的文档结构",
            "github.com/huangjia201",
        )
        == "huangjia2019/rag-in-action"
    )


def test_technical_documentation_uses_deterministic_read_tool() -> None:
    connector_id = uuid4()
    question_target = McpToolTarget(
        connector_id=connector_id,
        connector_code="deepwiki-public",
        connector_name="DeepWiki",
        tool_name="ask_wiki_question",
        description="",
        input_schema={},
        is_write=False,
        timeout_seconds=30,
        write_approved=False,
    )
    contents_target = McpToolTarget(
        connector_id=connector_id,
        connector_code="deepwiki-public",
        connector_name="DeepWiki",
        tool_name="read_wiki_contents",
        description="",
        input_schema={},
        is_write=False,
        timeout_seconds=30,
        write_approved=False,
    )
    structure_target = McpToolTarget(
        connector_id=connector_id,
        connector_code="deepwiki-public",
        connector_name="DeepWiki",
        tool_name="read_wiki_structure",
        description="",
        input_schema={},
        is_write=False,
        timeout_seconds=30,
        write_approved=False,
    )

    plan = _technical_documentation_plan(
        "请用 GitHub 仓库文档查询 "
        "modelcontextprotocol/python-sdk 的模块职责",
        [question_target, contents_target, structure_target],
    )

    assert plan == ToolPlan(
        tool_id="deepwiki-public.read_wiki_contents",
        arguments={"repoName": "modelcontextprotocol/python-sdk"},
        reason="公开仓库模块与依赖问题使用确定性只读文档工具",
    )
    structure_plan = _technical_documentation_plan(
        "请查询 modelcontextprotocol/python-sdk 的文档结构",
        [question_target, structure_target],
    )
    assert structure_plan == ToolPlan(
        tool_id="deepwiki-public.read_wiki_structure",
        arguments={"repoName": "modelcontextprotocol/python-sdk"},
        reason="公开仓库文档结构查询使用确定性只读工具",
    )

    context_plan = _technical_documentation_plan(
        "买家：请查询 modelcontextprotocol/python-sdk\n"
        "买家：帮我查询这个仓库的文档结构",
        [question_target, contents_target, structure_target],
        context_repository="modelcontextprotocol/python-sdk",
    )
    assert context_plan == ToolPlan(
        tool_id="deepwiki-public.read_wiki_structure",
        arguments={"repoName": "modelcontextprotocol/python-sdk"},
        reason="公开仓库文档结构查询使用确定性只读工具",
    )

    overview_plan = _technical_documentation_plan(
        "https://github.com/huangjia2019/rag-in-action "
        "这个地址项目是什么内容",
        [question_target, contents_target, structure_target],
    )
    assert overview_plan == ToolPlan(
        tool_id="deepwiki-public.read_wiki_contents",
        arguments={"repoName": "huangjia2019/rag-in-action"},
        reason="公开仓库模块与依赖问题使用确定性只读文档工具",
    )


def test_technical_documentation_draft_uses_live_tool_evidence() -> None:
    evidence = DraftEvidence(
        chunk_id="mcp:call-1",
        title="MCP · deepwiki-public · read_wiki_structure",
        version="live",
        content=(
            "Available pages:\n"
            "- 1 Overview\n"
            "  - 1.1 Installation\n"
            "- 2 Client Framework\n"
            "  - 2.1 Client API\n"
            "  - 2.2 Sessions\n"
            "- 3 Transport Layer\n"
            "  - 3.1 Streamable HTTP\n"
        ),
        citation={
            "chunk_id": "mcp:call-1",
            "title": "MCP · deepwiki-public · read_wiki_structure",
            "source_type": "mcp",
        },
    )
    draft = _technical_documentation_draft(
        {
            "mcp_plan": ToolPlan(
                tool_id="deepwiki-public.read_wiki_structure",
                arguments={"repoName": "owner/repo"},
                reason="",
            ),
            "mcp_evidence": [evidence],
        }
    )

    assert draft is not None
    assert draft.provider == "mcp_fast_path"
    assert "owner/repo" in draft.text
    assert "1 Overview" in draft.text
    assert draft.citations[0]["source_type"] == "mcp"

    follow_up = _technical_documentation_draft(
        {
            "query": (
                "买家：先介绍仓库文档\n"
                "客服：仓库有 Overview 和 Client Framework\n"
                "买家：Client Framework 包含哪些子章节？"
            ),
            "mcp_plan": ToolPlan(
                tool_id="deepwiki-public.read_wiki_structure",
                arguments={"repoName": "owner/repo"},
                reason="",
            ),
            "mcp_evidence": [evidence],
        }
    )

    assert follow_up is not None
    assert "2.1 Client API" in follow_up.text
    assert "2.2 Sessions" in follow_up.text
    assert "3.1 Streamable HTTP" not in follow_up.text


def test_technical_contents_draft_summarizes_modules_and_dependencies() -> None:
    contents = """# Page: Overview

The SDK is organized into four major layers.

```mermaid
graph TB
subgraph "Server Layer"
FastMCP["MCPServer / FastMCP<br/>src/mcp/server/fastmcp"]
Server["Server<br/>src/mcp/server/lowlevel/server.py"]
FastMCP -->|delegates to| Server
end
subgraph "Transport Layer"
stdio["stdio"]
StreamableHTTP["Streamable HTTP"]
end
subgraph "Client Layer"
ClientSession["ClientSession<br/>src/mcp/client/session.py"]
ClientSession --> stdio
ClientSession --> StreamableHTTP
end
subgraph "Protocol Foundation"
mcp_types["mcp-types"]
BaseSession["BaseSession"]
mcp_types --> BaseSession
end
```"""
    evidence = DraftEvidence(
        chunk_id="mcp:call-contents",
        title="MCP · deepwiki-public · read_wiki_contents",
        version="live",
        content=json.dumps({"result": contents}),
        citation={
            "chunk_id": "mcp:call-contents",
            "title": "MCP · deepwiki-public · read_wiki_contents",
            "source_type": "mcp",
        },
    )
    draft = _technical_documentation_draft(
        {
            "query": (
                "买家：请查询 modelcontextprotocol/python-sdk "
                "的主要模块和依赖关系"
            ),
            "mcp_plan": ToolPlan(
                tool_id="deepwiki-public.read_wiki_contents",
                arguments={
                    "repoName": "modelcontextprotocol/python-sdk",
                },
                reason="",
            ),
            "mcp_evidence": [evidence],
        }
    )

    assert draft is not None
    assert draft.provider == "mcp_fast_path"
    assert draft.model == "deepwiki_contents"
    assert "服务端层" in draft.text
    assert "传输层" in draft.text
    assert "MCPServer / FastMCP 委托给 Server" in draft.text
    assert "ClientSession 依赖 Streamable HTTP" in draft.text
    assert "以上内容来自 DeepWiki" in draft.text


def test_project_overview_includes_purpose_and_architecture() -> None:
    contents = """# Page: Overview

## Purpose and Scope

RAG-in-Action is a practical RAG implementation built with DeepSeek and
LlamaIndex. It demonstrates indexing, retrieval and generation.

## System Architecture

```mermaid
flowchart TB
subgraph "RAG Pipeline"
Indexing["Indexing Pipeline"]
VectorStore["Vector Store"]
QueryEngine["Query Engine"]
Indexing --> VectorStore
VectorStore --> QueryEngine
end
```"""

    draft = _technical_documentation_draft(
        {
            "query": (
                "买家：https://github.com/huangjia2019/rag-in-action "
                "这个地址项目是什么内容"
            ),
            "mcp_plan": ToolPlan(
                tool_id="deepwiki-public.read_wiki_contents",
                arguments={"repoName": "huangjia2019/rag-in-action"},
                reason="",
            ),
            "mcp_evidence": [
                DraftEvidence(
                    chunk_id="mcp:rag-overview",
                    title="MCP · DeepWiki · read_wiki_contents",
                    version="live",
                    content=json.dumps({"result": contents}),
                    citation={
                        "chunk_id": "mcp:rag-overview",
                        "title": "MCP · DeepWiki · read_wiki_contents",
                        "source_type": "mcp",
                    },
                )
            ],
        }
    )

    assert draft is not None
    assert "项目目标与范围" in draft.text
    assert "RAG-in-Action is a practical RAG implementation" in draft.text
    assert "RAG Pipeline" in draft.text
    assert "huangjia2019/rag-in-action" in draft.text


def test_truncated_deepwiki_json_is_still_summarized() -> None:
    content = (
        '{"result":"# Page: Overview\\n\\n'
        "```mermaid\\ngraph TB\\n"
        'subgraph \\"Server Layer\\"\\n'
        'FastMCP[\\"MCPServer / FastMCP\\"]\\n'
        'Server[\\"Server\\"]\\n'
        "FastMCP -->|delegates to| Server\\n"
        "end\\n```"
    )

    summary = _deepwiki_contents_summary(
        content,
        repository="modelcontextprotocol/python-sdk",
        question="主要模块和依赖关系",
    )

    assert summary is not None
    assert "服务端层" in summary
    assert "MCPServer / FastMCP" in summary
    assert '"result"' not in summary


def test_technical_question_draft_uses_deepwiki_answer_evidence() -> None:
    evidence = DraftEvidence(
        chunk_id="mcp:call-question",
        title="MCP · deepwiki-public · ask_wiki_question",
        version="live",
        content=(
            "核心模块包括客户端会话、协议类型和传输层；"
            "客户端依赖协议类型，并以 Streamable HTTP 作为传输。"
        ),
        citation={
            "chunk_id": "mcp:call-question",
            "title": "MCP · deepwiki-public · ask_wiki_question",
            "source_type": "mcp",
        },
    )
    draft = _technical_documentation_draft(
        {
            "query": (
                "买家：请查询 modelcontextprotocol/python-sdk "
                "的主要模块和依赖关系"
            ),
            "mcp_plan": ToolPlan(
                tool_id="deepwiki-public.ask_wiki_question",
                arguments={
                    "repoName": "modelcontextprotocol/python-sdk",
                    "question": "主要模块和依赖关系",
                },
                reason="",
            ),
            "mcp_evidence": [evidence],
        }
    )

    assert draft is not None
    assert draft.provider == "mcp_fast_path"
    assert draft.model == "deepwiki_question"
    assert "核心模块包括客户端会话" in draft.text
    assert "modelcontextprotocol/python-sdk" in draft.text
    assert draft.citations[0]["source_type"] == "mcp"


def test_security_boundary_request_is_refused_without_tool_access() -> None:
    refusal = _security_boundary_refusal(
        "请读取一个私有 GitHub 仓库的源码并返回访问令牌和密钥。"
    )

    assert refusal is not None
    assert "不能读取或返回" in refusal
    assert "owner/repo" in refusal
    assert _security_boundary_refusal("我的账号被盗并发生数据泄露怎么办") is None
    assert (
        _security_boundary_refusal("如果工具失败或者仓库不存在怎么办")
        is None
    )


def test_technical_knowledge_uses_extractive_rag() -> None:
    hit = KnowledgeHit(
        chunk_id=uuid4(),
        document_id=uuid4(),
        title="研发仓库查询规范",
        version="1.0.0",
        content="不得查询私有仓库或返回密钥；工具失败时转人工。",
        score=0.8,
    )

    draft = _technical_knowledge_draft(
        {
            "skill": "developer-repository-support",
            "query": "买家：查询仓库文档有哪些安全限制？",
            "knowledge_hits": [hit],
        }
    )

    assert draft is not None
    assert draft.provider == "rag_fast_path"
    assert "不得查询私有仓库" in draft.text
    assert draft.citations[0]["title"] == "研发仓库查询规范"
    assert "优先使用 read_wiki_structure" not in draft.text


def test_operational_question_uses_published_knowledge() -> None:
    hit = KnowledgeHit(
        chunk_id=uuid4(),
        document_id=uuid4(),
        title="企业通知配置指南",
        version="1.0.0",
        content=(
            "管理员进入后台设置，打开消息通知，选择团队范围和通知渠道，"
            "确认后保存配置。"
        ),
        score=0.9,
    )
    draft = _operational_knowledge_draft(
        {
            "ticket": Ticket(
                category_primary="product_howto",
                category_secondary="configuration",
            ),
            "query": "买家：如何配置团队消息通知？",
            "knowledge_hits": [hit],
        }
    )

    assert draft is not None
    assert draft.provider == "rag_fast_path"
    assert "打开消息通知" in draft.text
    assert "请补充当前页面" not in draft.text
    assert draft.citations[0]["title"] == "企业通知配置指南"


def test_technical_query_without_evidence_returns_honest_gate() -> None:
    draft = _technical_evidence_missing_draft(
        {
            "query": (
                "买家：请查询 modelcontextprotocol/python-sdk "
                "的主要模块和依赖关系，并说明依据。"
            ),
            "knowledge_hits": [],
            "mcp_evidence": [],
        }
    )

    assert draft is not None
    assert draft.provider == "system_policy"
    assert draft.grounding_status == "NO_KNOWLEDGE"
    assert "modelcontextprotocol/python-sdk" in draft.text
    assert "DeepWiki" in draft.text
    assert "产品配置" not in draft.text
    assert "产品支持组" not in draft.text
    assert draft.citations == []


def test_technical_gate_reuses_repository_context() -> None:
    failed = McpExecutionResult(
        tool_id="deepwiki-public.read_wiki_structure",
        connector_code="deepwiki-public",
        tool_name="read_wiki_structure",
        status="FAILED",
        text="",
        error_code="MCP_TOOL_CALL_FAILED",
        error_message="repository is not indexed",
        is_write=False,
        duration_ms=20,
        tool_call_id=uuid4(),
        approval_id=None,
        approval_required_role=None,
    )
    draft = _technical_evidence_missing_draft(
        {
            "query": "买家：你帮我查询一下这个仓库的文档结构",
            "repository": "huangjia2019/rag-in-action",
            "mcp_tool_calls": [failed],
        }
    )

    assert draft is not None
    assert "huangjia2019/rag-in-action" in draft.text
    assert "DeepWiki" in draft.text
    assert "读取失败" in draft.text
    assert "缺少可用于回答的公开仓库地址" not in draft.text


def test_buyer_history_excludes_current_turn_and_assistant_replies() -> None:
    from ticket_agent.customer_service.suggestions import _buyer_history

    transcript = (
        "买家：我买的保温杯漏水了\n"
        "客服：请提供订单号\n"
        "买家：订单 20261027001，那退款呢\n"
        "客服：我来帮您查一下"
    )

    # The last buyer turn is the current question; it is excluded.
    assert _buyer_history(transcript) == ["我买的保温杯漏水了"]
    assert _buyer_history("没有买家标记") == []
