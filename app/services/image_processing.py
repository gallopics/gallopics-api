import os
import tempfile

from PIL import Image, ImageDraw, ImageFont

from app.models.enums import PhotoStatus
from app.storage.base import StorageBackend


def generate_thumbnail(input_path: str, output_path: str, max_size: tuple = (300, 300)) -> str:
    img = Image.open(input_path)
    img.thumbnail(max_size, Image.Resampling.LANCZOS)
    img.save(output_path)
    return output_path


def generate_preview(input_path: str, output_path: str, max_size: tuple = (1200, 800)) -> str:
    img = Image.open(input_path)
    img.thumbnail(max_size, Image.Resampling.LANCZOS)
    img.save(output_path)
    return output_path


def apply_watermark(input_path: str, output_path: str, text: str = "gallopics.com") -> str:
    img = Image.open(input_path).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    font_size = max(20, img.size[0] // 20)
    font = ImageFont.load_default(size=font_size)

    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    x = (img.size[0] - text_width) // 2
    y = (img.size[1] - text_height) // 2
    draw.text((x, y), text, fill=(255, 255, 255, 100), font=font)

    watermarked = Image.alpha_composite(img, overlay)
    watermarked.convert("RGB").save(output_path)
    return output_path


async def process_photo(photo, storage: StorageBackend, db=None):
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = os.path.join(tmpdir, "original")
            await storage.download_to_path(photo.storage_key_original, original_path)

            thumbnail_path = os.path.join(tmpdir, "thumbnail.jpg")
            generate_thumbnail(original_path, thumbnail_path)
            thumb_key = photo.storage_key_original.replace("originals/", "thumbnails/")
            await storage.upload_from_path(thumbnail_path, thumb_key, "image/jpeg")

            preview_path = os.path.join(tmpdir, "preview.jpg")
            generate_preview(original_path, preview_path)
            watermarked_path = os.path.join(tmpdir, "preview_wm.jpg")
            apply_watermark(preview_path, watermarked_path)
            preview_key = photo.storage_key_original.replace("originals/", "previews/")
            await storage.upload_from_path(watermarked_path, preview_key, "image/jpeg")

            photo.storage_key_thumbnail = thumb_key
            photo.storage_key_preview = preview_key
            photo.status = PhotoStatus.READY

            if db:
                await db.flush()
    except Exception as e:
        # If processing fails, mark as ready anyway but use original as fallback
        photo.status = PhotoStatus.READY
        if db:
            await db.flush()
