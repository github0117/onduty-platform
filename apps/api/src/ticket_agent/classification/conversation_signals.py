import re
from typing import Literal

SmallTalkKind = Literal[
    "greeting",
    "thanks",
    "farewell",
    "identity",
    "clarification",
]

_REPOSITORY_PATTERN = re.compile(
    r"(?<![\w.-])([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(?![\w./-])"
)
_GITHUB_URL_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/"
    r"([A-Za-z0-9-]+)/([A-Za-z0-9_.-]+)",
    flags=re.IGNORECASE,
)
_TECHNICAL_STRONG_TERMS = (
    "github",
    "gitlab",
    "代码仓库",
    "仓库文档",
    "仓库结构",
    "仓库的文档",
    "仓库内容",
    "这个仓库",
    "当前项目",
    "项目文档",
    "项目内容",
    "技术文档",
    "模块职责",
    "主要模块",
    "模块和依赖",
    "依赖关系",
    "依赖项",
    "哪些依赖",
    "包依赖",
    "依赖包",
    "代码结构",
    "源代码",
    "open source repository",
    "api 文档",
    "接口文档",
    "sdk",
    "mcp",
    "package dependency",
    "package dependencies",
)
_TECHNICAL_CONTEXT_TERMS = (
    "代码",
    "仓库",
    "项目",
    "文档",
    "架构",
    "包",
    "组件",
    "接口",
    "研发",
    "开发",
)
_WEAK_TECHNICAL_TERMS = (
    "模块",
    "依赖",
    "api",
)
_GREETING_PHRASES = {
    "你好",
    "您好",
    "哈喽",
    "在吗",
    "hi",
    "hello",
}
_THANKS_PHRASES = {"谢谢", "多谢", "感谢"}
_FAREWELL_PHRASES = {"再见", "拜拜"}
_IDENTITY_PHRASES = {
    "你是谁",
    "你是什么",
    "你是什么身份",
    "你叫什么",
    "你叫什么名字",
    "介绍一下你",
    "介绍一下你自己",
    "介绍下你",
    "介绍下你自己",
    "你能做什么",
    "你会做什么",
    "你可以做什么",
    "你能帮我什么",
    "你能帮我做什么",
    "你有什么能力",
    "你有哪些能力",
    "你有啥能力",
    "你能处理什么",
    "你负责什么",
    "你是ai吗",
    "你是机器人吗",
}
_CLARIFICATION_PHRASES = {
    "帮我看看",
    "请帮我看看",
    "帮忙看看",
    "我有个问题",
    "咨询一下",
    "有个问题",
    "想问一下",
}


def normalize_user_text(text: str) -> str:
    normalized = " ".join(text.strip().casefold().split())
    return normalized.rstrip("！!。.?？")


def repository_name(text: str) -> str | None:
    url_match = _GITHUB_URL_PATTERN.search(text)
    if url_match is not None:
        repository = (
            f"{url_match.group(1)}/{url_match.group(2)}"
            .removesuffix(".git")
            .strip(".,;:!?，。；：！？")
        )
        return repository
    match = _REPOSITORY_PATTERN.search(text)
    if match is None:
        return None
    repository = match.group(1).removesuffix(".git")
    owner, _, _repository = repository.partition("/")
    if (
        repository.casefold() == "owner/repo"
        or owner.casefold() == "github.com"
        or "." in owner
    ):
        return None
    return repository


def is_technical_documentation_question(text: str) -> bool:
    lowered = text.casefold()
    if repository_name(lowered) is not None:
        return True
    if any(term in lowered for term in _TECHNICAL_STRONG_TERMS):
        return True
    if (
        any(
            pronoun in lowered
            for pronoun in (
                "它",
                "这个项目",
                "该项目",
                "这个仓库",
                "该仓库",
            )
        )
        and any(term in lowered for term in _WEAK_TECHNICAL_TERMS)
    ):
        return True
    return any(
        term in lowered
        for term in _WEAK_TECHNICAL_TERMS
    ) and any(
        term in lowered
        for term in _TECHNICAL_CONTEXT_TERMS
    )


def classify_small_talk(text: str) -> SmallTalkKind | None:
    normalized = normalize_user_text(text)
    if normalized in _THANKS_PHRASES:
        return "thanks"
    if normalized in _FAREWELL_PHRASES:
        return "farewell"
    if normalized in _IDENTITY_PHRASES:
        return "identity"
    if normalized in _CLARIFICATION_PHRASES:
        return "clarification"
    if normalized in _GREETING_PHRASES:
        return "greeting"
    return None
