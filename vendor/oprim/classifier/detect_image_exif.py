"""Detect EXIF metadata and basic properties from image files."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import ExifTags, Image, UnidentifiedImageError

from oprim._logging import log as olog
from oprim.errors import UnsupportedImageError


@dataclass
class ImageExif:
    has_exif: bool
    camera_make: str | None
    camera_model: str | None
    datetime_taken: str | None
    width: int
    height: int
    is_screenshot_likely: bool


# Common screen resolutions that may indicate a screenshot
_SCREEN_SIZES: frozenset[tuple[int, int]] = frozenset({
    (1920, 1080), (2560, 1440), (3024, 1964), (2560, 1600),
    (1440, 900), (2880, 1800), (1366, 768), (1280, 800),
    (3840, 2160), (2732, 2048), (2224, 1668),
})


def detect_image_exif(path: Path) -> ImageExif:
    """Return EXIF info and dimensions for an image file.

    Raises:
        FileNotFoundError: path does not exist.
        UnsupportedImageError: file cannot be opened as an image.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    try:
        img = Image.open(str(path))
        img.verify()          # integrity check
        img = Image.open(str(path))  # re-open after verify (verify closes)
    except (UnidentifiedImageError, Exception) as e:
        raise UnsupportedImageError(f"Cannot open image {path}: {e}") from e

    width, height = img.size
    fmt = img.format or ""

    # EXIF extraction
    camera_make: str | None = None
    camera_model: str | None = None
    datetime_taken: str | None = None
    has_exif = False

    try:
        raw_exif = img._getexif()  # type: ignore[attr-defined]
        if raw_exif:
            has_exif = True
            # Build tag-name → tag-id mapping
            tag_map = {v: k for k, v in ExifTags.TAGS.items()}
            make_tag = tag_map.get("Make", 0x010F)
            model_tag = tag_map.get("Model", 0x0110)
            dt_tag = tag_map.get("DateTimeOriginal", 0x9003)
            camera_make = raw_exif.get(make_tag) or raw_exif.get(0x010F)
            camera_model = raw_exif.get(model_tag) or raw_exif.get(0x0110)
            datetime_taken = raw_exif.get(dt_tag) or raw_exif.get(0x9003)
            if camera_make:
                camera_make = str(camera_make).strip()
            if camera_model:
                camera_model = str(camera_model).strip()
    except (AttributeError, Exception):
        pass

    # Screenshot heuristic: PNG + no EXIF + matches a common screen resolution
    is_screenshot_likely = (
        fmt.upper() == "PNG"
        and not has_exif
        and (width, height) in _SCREEN_SIZES
    )

    img.close()
    result = ImageExif(
        has_exif=has_exif,
        camera_make=camera_make,
        camera_model=camera_model,
        datetime_taken=str(datetime_taken) if datetime_taken else None,
        width=width,
        height=height,
        is_screenshot_likely=is_screenshot_likely,
    )
    olog.emit("detect_image_exif", path=str(path), result=str(result))
    return result
