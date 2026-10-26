import hashlib
import hmac
from datetime import UTC, datetime
from urllib.parse import quote, urlparse

import httpx

from ticket_agent.storage.types import ObjectStorageError


class S3ObjectStorage:
    """Minimal path-style S3 client with AWS Signature Version 4."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str,
        client: httpx.Client | None = None,
    ) -> None:
        self.endpoint_url = endpoint_url.rstrip("/")
        self.access_key = access_key
        self.secret_key = secret_key
        self.bucket = bucket
        self.region = region
        self._client = client or httpx.Client(timeout=20)
        self._bucket_ready = False

    def put_object(self, *, key: str, data: bytes, content_type: str) -> None:
        response = self._request(
            "PUT",
            self._object_path(key),
            data=data,
            content_type=content_type,
        )
        if response.status_code == 404:
            self._ensure_bucket()
            response = self._request(
                "PUT",
                self._object_path(key),
                data=data,
                content_type=content_type,
            )
        self._raise_for_status(response, "PUT", key)

    def get_object(self, *, key: str) -> bytes:
        response = self._request("GET", self._object_path(key))
        self._raise_for_status(response, "GET", key)
        return response.content

    def delete_object(self, *, key: str) -> None:
        response = self._request("DELETE", self._object_path(key))
        if response.status_code not in {204, 404}:
            self._raise_for_status(response, "DELETE", key)

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        response = self._request("PUT", f"/{quote(self.bucket, safe='-_.~')}")
        if response.status_code not in {200, 409}:
            self._raise_for_status(response, "PUT", self.bucket)
        self._bucket_ready = True

    def _request(
        self,
        method: str,
        path: str,
        *,
        data: bytes = b"",
        content_type: str = "",
    ) -> httpx.Response:
        now = datetime.now(UTC)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        payload_hash = hashlib.sha256(data).hexdigest()
        parsed = urlparse(self.endpoint_url)
        host = parsed.netloc

        headers = {
            "host": host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }
        if content_type:
            headers["content-type"] = content_type

        sorted_headers = sorted(headers.items())
        canonical_headers = "".join(f"{key}:{value.strip()}\n" for key, value in sorted_headers)
        signed_headers = ";".join(key for key, _ in sorted_headers)
        canonical_request = "\n".join(
            [
                method,
                path,
                "",
                canonical_headers,
                signed_headers,
                payload_hash,
            ]
        )
        credential_scope = f"{date_stamp}/{self.region}/s3/aws4_request"
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                credential_scope,
                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
            ]
        )
        signing_key = self._signing_key(date_stamp)
        signature = hmac.new(
            signing_key,
            string_to_sign.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        headers["Authorization"] = (
            "AWS4-HMAC-SHA256 "
            f"Credential={self.access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        try:
            return self._client.request(
                method,
                f"{self.endpoint_url}{path}",
                headers=headers,
                content=data if method == "PUT" else None,
            )
        except httpx.HTTPError as exc:
            raise ObjectStorageError(f"S3 request failed: {type(exc).__name__}") from exc

    def _signing_key(self, date_stamp: str) -> bytes:
        date_key = hmac.new(
            f"AWS4{self.secret_key}".encode(),
            date_stamp.encode(),
            hashlib.sha256,
        ).digest()
        region_key = hmac.new(date_key, self.region.encode(), hashlib.sha256).digest()
        service_key = hmac.new(region_key, b"s3", hashlib.sha256).digest()
        return hmac.new(service_key, b"aws4_request", hashlib.sha256).digest()

    def _object_path(self, key: str) -> str:
        return f"/{quote(self.bucket, safe='-_.~')}/{quote(key, safe='/-_.~')}"

    @staticmethod
    def _raise_for_status(response: httpx.Response, method: str, key: str) -> None:
        if response.is_success:
            return
        raise ObjectStorageError(
            f"S3 {method} {key} failed with HTTP {response.status_code}"
        )

