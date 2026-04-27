from app.storage.base import StorageBackend


class S3StorageBackend(StorageBackend):
    def __init__(self, settings):
        self.bucket = settings.storage_s3_bucket
        self.region = settings.storage_s3_region

    async def generate_presigned_upload_url(self, key: str, content_type: str, expires_in: int = 3600) -> str:
        raise NotImplementedError("S3 backend not yet implemented")

    async def generate_presigned_download_url(self, key: str, expires_in: int = 3600) -> str:
        raise NotImplementedError("S3 backend not yet implemented")

    async def download_to_path(self, key: str, local_path: str) -> None:
        raise NotImplementedError("S3 backend not yet implemented")

    async def upload_from_path(self, local_path: str, key: str, content_type: str) -> None:
        raise NotImplementedError("S3 backend not yet implemented")

    async def delete_object(self, key: str) -> None:
        raise NotImplementedError("S3 backend not yet implemented")

    async def object_exists(self, key: str) -> bool:
        raise NotImplementedError("S3 backend not yet implemented")
