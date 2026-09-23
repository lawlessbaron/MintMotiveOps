import os
import uuid
from flask import current_app

IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "bmp"}

# "Documents" covers everything people actually attach in this app: office
# paperwork, CAD/Inventor mechanical design files, and Arduino/embedded
# source. Anything not on this list is rejected outright — an allowlist,
# not a denylist, since uploaded files are served straight back out of
# /static/uploads with no sandboxing (see save_upload below).
DOCUMENT_EXTENSIONS = IMAGE_EXTENSIONS | {
    # office / paperwork
    "pdf", "doc", "docx", "xls", "xlsx", "csv", "txt", "rtf", "odt", "ods",
    # CAD / Inventor / mechanical design
    "ipt", "iam", "idw", "ipn", "step", "stp", "iges", "igs", "stl", "dxf",
    "dwg", "f3d", "sldprt", "sldasm", "slddrw", "3mf",
    # Arduino / embedded source
    "ino", "h", "hpp", "cpp", "c", "zip",
}

# Kit Firmware Versions — the actual flashable artifact, not source.
FIRMWARE_EXTENSIONS = {"bin", "hex", "uf2", "elf", "ino"}

# Subfolders that only ever hold a product/kit/build/company-logo photo.
IMAGE_ONLY_SUBFOLDERS = {"company", "parts", "kits", "builds", "sourcing"}
DOCUMENT_SUBFOLDERS = {"documents"}
FIRMWARE_SUBFOLDERS = {"firmware"}


def save_upload(file_storage, subfolder):
    """Saves an uploaded file under instance/uploads/<subfolder>/ and returns
    a path relative to /static (served via the /uploads static route) or
    None if nothing was uploaded or its extension isn't on the relevant
    allowlist above."""
    if not file_storage or not file_storage.filename:
        return None
    ext = file_storage.filename.rsplit(".", 1)[-1].lower() if "." in file_storage.filename else ""
    if subfolder in IMAGE_ONLY_SUBFOLDERS and ext not in IMAGE_EXTENSIONS:
        return None
    if subfolder in DOCUMENT_SUBFOLDERS and ext not in DOCUMENT_EXTENSIONS:
        return None
    if subfolder in FIRMWARE_SUBFOLDERS and ext not in FIRMWARE_EXTENSIONS:
        return None
    fname = f"{uuid.uuid4().hex}.{ext}" if ext else uuid.uuid4().hex
    folder = os.path.join(current_app.static_folder, "uploads", subfolder)
    os.makedirs(folder, exist_ok=True)
    file_storage.save(os.path.join(folder, fname))
    return f"uploads/{subfolder}/{fname}"
