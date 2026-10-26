import json
from typing import Any

from sqlalchemy import JSON
from sqlalchemy.types import TypeDecorator, UserDefinedType


class PostgresVector(UserDefinedType[list[float]]):
    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        super().__init__()
        self.dimensions = dimensions

    def get_col_spec(self, **kw: object) -> str:
        return f"vector({self.dimensions})"

    def bind_processor(self, dialect: Any) -> Any:
        del dialect

        def process(value: list[float] | str | None) -> str | None:
            if value is None or isinstance(value, str):
                return value
            return json.dumps(value, separators=(",", ":"))

        return process

    def result_processor(self, dialect: Any, coltype: object) -> Any:
        del dialect, coltype

        def process(
            value: str | list[float] | tuple[float, ...] | None,
        ) -> list[float] | None:
            if value is None:
                return None
            parsed = json.loads(value) if isinstance(value, str) else value
            return [float(item) for item in parsed]

        return process


class EmbeddingVector(TypeDecorator[list[float]]):
    """Store pgvector on PostgreSQL and JSON on SQLite for local tests."""

    impl = JSON
    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        super().__init__()
        self.dimensions = dimensions

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PostgresVector(self.dimensions))
        return dialect.type_descriptor(JSON())

