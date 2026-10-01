"""Image-format sniffing for the ``vision`` capability.

Figure crops come from ``app.documents.figures`` in whatever format PyMuPDF
extracted them as (PNG/JPEG/etc. — see ``extract_image``'s ``ext``), so
``vision(image: bytes, ...)`` can't assume a fixed mime type. Uses Pillow
(already a pinned dependency for OCR) rather than adding an image-sniffing
library for this.
"""

import io

from PIL import Image, UnidentifiedImageError

_MIME_BY_PIL_FORMAT = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "GIF": "image/gif",
    "WEBP": "image/webp",
    "BMP": "image/bmp",
}


def detect_image_mime_type(image: bytes) -> str:
    """Raises ``ValueError`` if ``image`` isn't a format providers accept."""
    try:
        with Image.open(io.BytesIO(image)) as img:
            fmt = img.format or ""
    except UnidentifiedImageError as exc:
        raise ValueError("Could not identify image format") from exc

    mime_type = _MIME_BY_PIL_FORMAT.get(fmt)
    if mime_type is None:
        raise ValueError(f"Unsupported image format for vision: {fmt or 'unknown'}")
    return mime_type
