import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from ticket_agent.storage.types import ObjectStorageError


class LocalObjectStorage:
    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put_object(self, *, key: str, data: bytes, content_type: str) -> None:
        del content_type
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=target.parent, delete=False) as temporary:
            temporary.write(data)
            temporary.flush()
            os.fsync(temporary.fileno())
            temp_path = Path(temporary.name)
        temp_path.replace(target)

    def get_object(self, *, key: str) -> bytes:
        target = self._path(key)
        try:
            return target.read_bytes()
        except FileNotFoundError as exc:
            raise ObjectStorageError(f"Object not found: {key}") from exc

    def delete_object(self, *, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def _path(self, key: str) -> Path:
        normalized = Path(key)
        if normalized.is_absolute() or ".." in normalized.parts:
            raise ObjectStorageError("Unsafe object key")
        target = (self.root / normalized).resolve()
        if self.root not in target.parents and target != self.root:
            raise ObjectStorageError("Object key escapes storage root")
        return target

