from functools import lru_cache

from ticket_agent.shared.settings import get_settings
from ticket_agent.storage.local import LocalObjectStorage
from ticket_agent.storage.s3 import S3ObjectStorage
from ticket_agent.storage.types import ObjectStorage


@lru_cache
def get_object_storage() -> ObjectStorage:
    settings = get_settings()
    if settings.object_storage_provider == "s3":
        return S3ObjectStorage(
            endpoint_url=settings.s3_endpoint_url,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            bucket=settings.s3_bucket,
            region=settings.s3_region,
        )
    return LocalObjectStorage(settings.object_storage_local_root)

