import asyncio
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image
from botocore.exceptions import ClientError

from app.services.download_service import download_bytes
from app.services.pricing import QUALITY_TIERS
from app.storage.s3 import S3StorageBackend


class FakeS3:
    def __init__(self, original):
        self.files = {"originals/photo.jpg": original}
        self.uploads = []

    def head_object(self, *, Bucket, Key):
        if Key not in self.files:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        return {}

    def download_file(self, bucket, key, path):
        Path(path).write_bytes(self.files[key])

    def upload_file(self, path, bucket, key, ExtraArgs):
        self.files[key] = Path(path).read_bytes()
        self.uploads.append(key)


async def test_s3_download_cache_uses_storage_once_for_concurrent_requests():
    from app.services.download_service import _resize_download
    image = BytesIO()
    Image.new("RGB", (1200, 1800), "blue").save(image, format="JPEG")
    storage = S3StorageBackend(SimpleNamespace(storage_s3_bucket="test", storage_s3_region="eu-north-1"))
    storage._s3 = FakeS3(image.getvalue())
    photo = SimpleNamespace(id="test-photo", storage_key_original="originals/photo.jpg")
    with patch("app.services.download_service._resize_download", wraps=_resize_download) as resize:
        first, second = await asyncio.gather(
            download_bytes(photo, QUALITY_TIERS["web"], storage),
            download_bytes(photo, QUALITY_TIERS["web"], storage),
        )
        assert resize.call_count == 1
    assert first == second
    assert Image.open(BytesIO(first)).size == (720, 1080)
    assert storage._s3.uploads == ["downloads/test-photo/web.jpg", "downloads/test-photo/web.json"]
    assert await download_bytes(photo, QUALITY_TIERS["high"], storage) == image.getvalue()
