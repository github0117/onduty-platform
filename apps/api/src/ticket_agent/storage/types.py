from typing import Protocol


class ObjectStorageError(RuntimeError):
    pass


class ObjectStorage(Protocol):
    def put_object(self, *, key: str, data: bytes, content_type: str) -> None: ...

    def get_object(self, *, key: str) -> bytes: ...

    def delete_object(self, *, key: str) -> None: ...

