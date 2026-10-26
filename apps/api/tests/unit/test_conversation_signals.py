import pytest

from ticket_agent.classification.conversation_signals import (
    classify_small_talk,
    is_technical_documentation_question,
    repository_name,
)


@pytest.mark.parametrize(
    "text",
    [
        "请查询 modelcontextprotocol/python-sdk 的主要模块和依赖关系",
        "这个 SDK 包含哪些模块？",
        "请说明 MCP Python 包的依赖关系",
        "看一下这个项目的代码结构与接口文档",
        "请用 GitHub 仓库文档说明模块职责",
        "它有哪些依赖关系？",
        "主要模块有哪些？",
        "有哪些依赖？",
        "你再查一下这个仓库的文档结构",
    ],
)
def test_technical_documentation_matrix(text: str) -> None:
    assert is_technical_documentation_question(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "如何配置消息通知",
        "退款什么时候到账",
        "我的快递到哪里了",
        "通知模块怎么配置",
        "帮我查一下订单",
    ],
)
def test_non_technical_business_queries_are_not_misclassified(
    text: str,
) -> None:
    assert is_technical_documentation_question(text) is False


@pytest.mark.parametrize(
    "text",
    [
        "你是谁",
        "你是谁？",
        "你能做什么",
        "你能帮我做什么？",
        "介绍一下你自己",
        "你是什么身份",
        "你是AI吗",
    ],
)
def test_identity_questions_are_deterministic_small_talk(
    text: str,
) -> None:
    assert classify_small_talk(text) == "identity"


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("你好", "greeting"),
        ("谢谢！", "thanks"),
        ("再见。", "farewell"),
        ("帮我看看", "clarification"),
        ("帮我查物流", None),
    ],
)
def test_small_talk_matrix(text: str, kind: str | None) -> None:
    assert classify_small_talk(text) == kind


def test_repository_name_requires_public_owner_repo_format() -> None:
    assert (
        repository_name(
            "请查询 modelcontextprotocol/python-sdk 的依赖关系"
        )
        == "modelcontextprotocol/python-sdk"
    )
    assert repository_name("请查询 owner/repo") is None
    assert repository_name("没有仓库地址") is None
    assert (
        repository_name(
            "https://github.com/huangjia2019/rag-in-action"
            " 这个地址项目是什么内容"
        )
        == "huangjia2019/rag-in-action"
    )
    assert repository_name("github.com/huangjia201") is None
