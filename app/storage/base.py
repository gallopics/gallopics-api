from abc import ABC, abstractmethod

from fastapi import UploadFile


class StorageBackend(ABC):
    @abstractmethod
    async def generate_presigned_upload_url(self, key: str, content_type: str, expires_in: int = 3600) -> str:
        ...

    @abstractmethod
    async def generate_presigned_download_url(self, key: str, expires_in: int = 3600) -> str:
        ...

    @abstractmethod
    async def download_to_path(self, key: str, local_path: str) -> None:
        ...

    @abstractmethod
    async def upload_from_path(self, local_path: str, key: str, content_type: str) -> None:
        ...

    @abstractmethod
    async def delete_object(self, key: str) -> None:
        ...

    @abstractmethod
    async def object_exists(self, key: str) -> bool:
        ...

    async def write_upload_file(self, file: UploadFile, key: str) -> str:
        raise NotImplementedError


def get_storage_backend(settings) -> StorageBackend:
    if settings.storage_backend == "s3":
        from app.storage.s3 import S3StorageBackend
        return S3StorageBackend(settings)
    else:
        from app.storage.local import LocalStorageBackend
        return LocalStorageBackend(settings.storage_local_path)
