import os
import tempfile

from PIL import Image

from app.services.image_processing import apply_watermark, generate_preview, generate_thumbnail


def _make_test_image(path: str, size=(2000, 1500)):
    img = Image.new("RGB", size, color="red")
    img.save(path)
    return path


def test_generate_thumbnail_correct_size():
    with tempfile.TemporaryDirectory() as d:
        src = _make_test_image(os.path.join(d, "src.jpg"))
        dst = os.path.join(d, "thumb.jpg")
        generate_thumbnail(src, dst, max_size=(300, 300))
        thumb = Image.open(dst)
        assert thumb.size[0] <= 300
        assert thumb.size[1] <= 300


def test_generate_thumbnail_maintains_aspect_ratio():
    with tempfile.TemporaryDirectory() as d:
        src = _make_test_image(os.path.join(d, "src.jpg"), size=(2000, 1000))
        dst = os.path.join(d, "thumb.jpg")
        generate_thumbnail(src, dst, max_size=(300, 300))
        thumb = Image.open(dst)
        ratio = thumb.size[0] / thumb.size[1]
        assert abs(ratio - 2.0) < 0.1


def test_generate_preview_correct_size():
    with tempfile.TemporaryDirectory() as d:
        src = _make_test_image(os.path.join(d, "src.jpg"))
        dst = os.path.join(d, "preview.jpg")
        generate_preview(src, dst, max_size=(1200, 800))
        preview = Image.open(dst)
        assert preview.size[0] <= 1200
        assert preview.size[1] <= 800


def test_apply_watermark_modifies_image():
    with tempfile.TemporaryDirectory() as d:
        src = _make_test_image(os.path.join(d, "src.jpg"))
        dst = os.path.join(d, "wm.jpg")
        apply_watermark(src, dst)
        # Watermarked file should exist and differ from source
        assert os.path.exists(dst)
        # Size should be preserved
        original = Image.open(src)
        watermarked = Image.open(dst)
        assert original.size == watermarked.size


def test_apply_watermark_preserves_dimensions():
    with tempfile.TemporaryDirectory() as d:
        src = _make_test_image(os.path.join(d, "src.jpg"), size=(800, 600))
        dst = os.path.join(d, "wm.jpg")
        apply_watermark(src, dst)
        result = Image.open(dst)
        assert result.size == (800, 600)
