import os
import uuid
from flask import current_app

ALLOWED_IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "webp"}
# Subfolders that only ever hold a product/kit/build photo — anything else
# (documents, firmware binaries, etc.) accepts any file extension, since
# there's no fixed list of valid firmware/document file types to check.
IMAGE_ONLY_SUBFOLDERS = {"parts", "kits", "builds", "sourcing"}


def save_upload(file_storage, subfolder):
    """Saves an uploaded file under instance/uploads/<subfolder>/ and returns
    a path relative to /static (served via the /uploads static route) or
    None if nothing was uploaded."""
    if not file_storage or not file_storage.filename:
        return None
    ext = file_storage.filename.rsplit(".", 1)[-1].lower() if "." in file_storage.filename else ""
    if subfolder in IMAGE_ONLY_SUBFOLDERS and ext not in ALLOWED_IMAGE_EXT:
        return None
    fname = f"{uuid.uuid4().hex}.{ext}" if ext else uuid.uuid4().hex
    folder = os.path.join(current_app.static_folder, "uploads", subfolder)
    os.makedirs(folder, exist_ok=True)
    file_storage.save(os.path.join(folder, fname))
    return f"uploads/{subfolder}/{fname}"
