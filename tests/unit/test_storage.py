import os
import tempfile

import pytest

from app.storage.base import get_storage_backend
from app.storage.local import LocalStorageBackend


@pytest.fixture
def local_storage(tmp_path):
    return LocalStorageBackend(str(tmp_path))


async def test_local_upload_and_download(local_storage, tmp_path):
    # Create a source file
    src = tmp_path / "source.txt"
    src.write_text("hello world")

    await local_storage.upload_from_path(str(src), "test/file.txt", "text/plain")
    assert await local_storage.object_exists("test/file.txt")

    dst = str(tmp_path / "downloaded.txt")
    await local_storage.download_to_path("test/file.txt", dst)
    assert open(dst).read() == "hello world"


async def test_local_presigned_upload_url(local_storage):
    url = await local_storage.generate_presigned_upload_url("key.jpg", "image/jpeg")
    assert url.startswith("file://")


async def test_local_presigned_download_url(local_storage):
    url = await local_storage.generate_presigned_download_url("key.jpg")
    assert url.startswith("file://")


async def test_local_delete(local_storage, tmp_path):
    src = tmp_path / "to_delete.txt"
    src.write_text("delete me")
    await local_storage.upload_from_path(str(src), "deletable.txt", "text/plain")
    assert await local_storage.object_exists("deletable.txt")

    await local_storage.delete_object("deletable.txt")
    assert not await local_storage.object_exists("deletable.txt")


async def test_local_object_exists_false(local_storage):
    assert not await local_storage.object_exists("nonexistent.txt")


def test_factory_returns_local():
    class FakeSettings:
        storage_backend = "local"
        storage_local_path = "/tmp/test_storage"

    backend = get_storage_backend(FakeSettings())
    assert isinstance(backend, LocalStorageBackend)


def test_factory_returns_s3():
    from app.storage.s3 import S3StorageBackend

    class FakeSettings:
        storage_backend = "s3"
        storage_s3_bucket = "bucket"
        storage_s3_region = "eu-north-1"

    backend = get_storage_backend(FakeSettings())
    assert isinstance(backend, S3StorageBackend)
