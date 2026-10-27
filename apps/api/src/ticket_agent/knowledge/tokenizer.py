import re

# CJK runs or latin/number runs that keep product codes and model numbers whole.
_TOKEN_PATTERN = re.compile(r"[\u4e00-\u9fff]+|[a-z0-9][a-z0-9_.\-/]*")
_LATIN_SEPARATORS = re.compile(r"[^a-z0-9]+")

_CJK_STOPWORDS = frozenset(
    [
        "的", "了", "和", "与", "及", "或", "在", "是", "有", "无", "不", "就", "都",
        "也", "而", "被", "把", "对", "从", "到", "为", "以", "于", "之", "其", "这",
        "那", "个", "们", "吗", "呢", "吧", "啊", "请", "我", "你", "他", "她", "它",
    ]
)

LEXICAL_TOKENIZER_VERSION = "v1"
MAX_QUERY_TOKENS = 32


def tokenize(text: str) -> list[str]:
    """Split mixed Chinese/latin text into lexical terms.

    Chinese is indexed as single characters plus bigrams so that both the
    stored lexical text and the query tsquery use the same vocabulary.
    """
    tokens: list[str] = []
    for match in _TOKEN_PATTERN.finditer(text.lower()):
        value = match.group(0)
        if "\u4e00" <= value[0] <= "\u9fff":
            tokens.extend(char for char in value if char not in _CJK_STOPWORDS)
            tokens.extend(
                value[index : index + 2]
                for index in range(len(value) - 1)
                # A bigram made only of stopword characters carries no meaning;
                # bigrams mixing one stopword character with a content character
                # are kept because compounds like 无理由 need them.
                if value[index] not in _CJK_STOPWORDS
                or value[index + 1] not in _CJK_STOPWORDS
            )
        else:
            tokens.append(value)
    return tokens


def build_lexical_text(text: str) -> str:
    return " ".join(tokenize(text))


def build_tsquery(query: str) -> str:
    """Turn a natural-language query into an OR tsquery over the same terms.

    Latin tokens are split on punctuation before being sent to ``to_tsquery``:
    PostgreSQL turns a hyphenated token into an adjacency phrase
    (``'hx-9080b' <-> 'hx' <-> '9080b'``), which would silently require the
    parts to be adjacent. Splitting keeps the query a plain OR while the index
    still stores the compound and its parts.
    """
    seen: list[str] = []
    for token in tokenize(query):
        parts = _LATIN_SEPARATORS.split(token) if token[0].isascii() else [token]
        for part in parts:
            if not part or part in seen:
                continue
            seen.append(part)
            if len(seen) >= MAX_QUERY_TOKENS:
                return " | ".join(seen)
    return " | ".join(seen)
