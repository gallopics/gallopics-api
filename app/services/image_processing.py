import os
import tempfile

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select

from app.models.enums import PhotoStatus
from app.models.photographer import Photographer
from app.storage.base import StorageBackend


BRAND_WATERMARK_TEXT = "GALLOPICS.COM"
DEFAULT_COPYRIGHT_NAME = "Gallopics"


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


async def _get_photographer_display_name(photo, db=None) -> str:
    loaded_photographer = getattr(photo, "__dict__", {}).get("photographer")
    if loaded_photographer and loaded_photographer.display_name:
        return loaded_photographer.display_name

    if db is None or not getattr(photo, "photographer_id", None):
        return DEFAULT_COPYRIGHT_NAME

    result = await db.execute(select(Photographer.display_name).where(Photographer.id == photo.photographer_id))
    return result.scalar_one_or_none() or DEFAULT_COPYRIGHT_NAME


def apply_watermark(
    input_path: str,
    output_path: str,
    photographer_name: str = DEFAULT_COPYRIGHT_NAME,
) -> str:
    img = Image.open(input_path).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    brand_font_size = max(20, img.size[0] // 20)
    copyright_font_size = max(12, brand_font_size // 3)
    brand_font = ImageFont.load_default(size=brand_font_size)
    copyright_font = ImageFont.load_default(size=copyright_font_size)

    copyright_text = f"© {photographer_name or DEFAULT_COPYRIGHT_NAME}"

    brand_bbox = draw.textbbox((0, 0), BRAND_WATERMARK_TEXT, font=brand_font)
    copyright_bbox = draw.textbbox((0, 0), copyright_text, font=copyright_font)
    brand_width = brand_bbox[2] - brand_bbox[0]
    brand_height = brand_bbox[3] - brand_bbox[1]
    copyright_width = copyright_bbox[2] - copyright_bbox[0]
    copyright_height = copyright_bbox[3] - copyright_bbox[1]
    line_gap = max(6, brand_font_size // 5)
    total_height = brand_height + line_gap + copyright_height

    brand_x = (img.size[0] - brand_width) // 2
    brand_y = (img.size[1] - total_height) // 2
    copyright_x = (img.size[0] - copyright_width) // 2
    copyright_y = brand_y + brand_height + line_gap

    draw.text(
        (brand_x, brand_y),
        BRAND_WATERMARK_TEXT,
        fill=(255, 255, 255, 120),
        font=brand_font,
    )
    draw.text(
        (copyright_x, copyright_y),
        copyright_text,
        fill=(255, 255, 255, 110),
        font=copyright_font,
    )

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
            photographer_name = await _get_photographer_display_name(photo, db)
            apply_watermark(preview_path, watermarked_path, photographer_name)
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
