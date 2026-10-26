from pathlib import Path

import httpx
import pytest

from ticket_agent.storage.local import LocalObjectStorage
from ticket_agent.storage.s3 import S3ObjectStorage
from ticket_agent.storage.types import ObjectStorageError


def test_local_storage_round_trip(tmp_path: Path) -> None:
    storage = LocalObjectStorage(str(tmp_path))

    storage.put_object(
        key="knowledge/bu/doc/file.md",
        data=b"hello",
        content_type="text/markdown",
    )

    assert storage.get_object(key="knowledge/bu/doc/file.md") == b"hello"
    storage.delete_object(key="knowledge/bu/doc/file.md")
    with pytest.raises(ObjectStorageError):
        storage.get_object(key="knowledge/bu/doc/file.md")


def test_local_storage_rejects_path_traversal(tmp_path: Path) -> None:
    storage = LocalObjectStorage(str(tmp_path))

    with pytest.raises(ObjectStorageError):
        storage.put_object(
            key="../escape.txt",
            data=b"bad",
            content_type="text/plain",
        )


def test_s3_storage_signs_put_and_get() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, content=b"s3-content")
        return httpx.Response(200)

    storage = S3ObjectStorage(
        endpoint_url="http://minio.example",
        access_key="access",
        secret_key="secret",
        bucket="knowledge",
        region="us-east-1",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    storage.put_object(
        key="docs/guide.md",
        data=b"hello",
        content_type="text/markdown",
    )
    assert storage.get_object(key="docs/guide.md") == b"s3-content"

    put_request = requests[0]
    assert put_request.url.path == "/knowledge/docs/guide.md"
    assert put_request.headers["Authorization"].startswith("AWS4-HMAC-SHA256")
    assert put_request.headers["x-amz-content-sha256"]

