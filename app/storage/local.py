import os
import shutil
from pathlib import Path

from app.storage.base import StorageBackend


class LocalStorageBackend(StorageBackend):
    def __init__(self, base_path: str):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _full_path(self, key: str) -> Path:
        path = self.base_path / key
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    async def generate_presigned_upload_url(self, key: str, content_type: str, expires_in: int = 3600) -> str:
        return f"file://{self._full_path(key)}"

    async def generate_presigned_download_url(self, key: str, expires_in: int = 3600) -> str:
        return f"file://{self._full_path(key)}"

    async def download_to_path(self, key: str, local_path: str) -> None:
        shutil.copy2(str(self._full_path(key)), local_path)

    async def upload_from_path(self, local_path: str, key: str, content_type: str) -> None:
        shutil.copy2(local_path, str(self._full_path(key)))

    async def delete_object(self, key: str) -> None:
        path = self._full_path(key)
        if path.exists():
            path.unlink()

    async def object_exists(self, key: str) -> bool:
        return self._full_path(key).exists()
