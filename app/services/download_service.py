import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from weakref import WeakValueDictionary

from PIL import Image, ImageOps

from app.services.pricing import QUALITY_TIERS, QualityTier
from app.storage.base import StorageBackend

_cache_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()


def download_cache_keys(photo_id) -> list[str]:
    return [f"downloads/{photo_id}/{quality}.{suffix}" for quality in QUALITY_TIERS for suffix in ("jpg", "json")]


def _resize_download(source: str, target: str, max_long_side: int) -> None:
    with Image.open(source) as original:
        image = ImageOps.exif_transpose(original).convert("RGB")
        image.thumbnail((max_long_side, max_long_side), Image.Resampling.LANCZOS)
        image.save(target, format="JPEG", quality=90)


async def download_bytes(photo, tier: QualityTier, storage: StorageBackend) -> bytes:
    with TemporaryDirectory() as tmpdir:
        original_path = Path(tmpdir) / "original"
        if tier.max_long_side is None:
            await storage.download_to_path(photo.storage_key_original, str(original_path))
            return await asyncio.to_thread(original_path.read_bytes)

        key = f"downloads/{photo.id}/{tier.id}.jpg"
        metadata_key = f"downloads/{photo.id}/{tier.id}.json"
        metadata_path = Path(tmpdir) / "metadata.json"
        resized_path = Path(tmpdir) / "download.jpg"
        # Invalidate cached derivatives when the single tier size setting changes.
        metadata = {"max_long_side": tier.max_long_side, "original": photo.storage_key_original}
        lock = _cache_locks.setdefault(key, asyncio.Lock())
        async with lock:
            cached = False
            if await storage.object_exists(key) and await storage.object_exists(metadata_key):
                await storage.download_to_path(metadata_key, str(metadata_path))
                try:
                    cached = json.loads(await asyncio.to_thread(metadata_path.read_text)) == metadata
                except (ValueError, UnicodeError):
                    pass
            if cached:
                await storage.download_to_path(key, str(resized_path))
            else:
                await storage.download_to_path(photo.storage_key_original, str(original_path))
                await asyncio.to_thread(_resize_download, str(original_path), str(resized_path), tier.max_long_side)
                await storage.upload_from_path(str(resized_path), key, "image/jpeg")
                await asyncio.to_thread(metadata_path.write_text, json.dumps(metadata))
                await storage.upload_from_path(str(metadata_path), metadata_key, "application/json")
            return await asyncio.to_thread(resized_path.read_bytes)
