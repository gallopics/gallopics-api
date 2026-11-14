import shutil
import threading
from types import SimpleNamespace

from app.models.enums import PhotoStatus
from app.services.image_processing import process_photo
from app.storage.local import LocalStorageBackend


async def test_process_photo_runs_all_pillow_steps_off_event_loop(monkeypatch, tmp_path):
    import app.services.image_processing as processing
    storage = LocalStorageBackend(str(tmp_path))
    source = tmp_path / "originals/photo.jpg"
    source.parent.mkdir()
    source.write_bytes(b"test-image")
    calls = []
    def pillow_step(source, target, *args):
        calls.append(threading.get_ident())
        shutil.copyfile(source, target)
    for name in ["generate_thumbnail", "generate_preview", "apply_watermark"]:
        monkeypatch.setattr(processing, name, pillow_step)
    photo = SimpleNamespace(storage_key_original="originals/photo.jpg", status=PhotoStatus.PROCESSING)
    await process_photo(photo, storage)
    assert len(calls) == 3
    assert all(thread != threading.get_ident() for thread in calls)
    assert photo.status == PhotoStatus.READY
    assert (tmp_path / photo.storage_key_preview).read_bytes() == b"test-image"
