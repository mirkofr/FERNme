"""Local image blob handling for default-off multimodal memory.

Image bytes remain outside the graph database. Pillow is imported lazily so
the deterministic text engine has no media dependency unless media is enabled.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Optional
import os
import shutil
import warnings


DEFAULT_MAX_BYTES = 25 * 1024 * 1024
DEFAULT_THUMBNAIL_MAX_PX = 512
ALLOWED_FORMATS = {
    "JPEG": ("image/jpeg", ".jpg"),
    "PNG": ("image/png", ".png"),
    "WEBP": ("image/webp", ".webp"),
}


class MediaError(RuntimeError):
    pass


class MediaDisabledError(MediaError):
    pass


class MediaDependencyError(MediaError):
    pass


@dataclass(frozen=True)
class MediaObject:
    id: str
    site: str
    user: str
    type: str
    mime: str
    uri: str
    sha256: str
    bytes: int
    created_ts: float
    source: str
    thumbnail_uri: str
    exif_stripped: bool
    sensitive: bool
    consent: bool
    status: str

    def row(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PreparedImage:
    source_sha256: str
    source_bytes: int
    mime: str
    extension: str
    clean_bytes: bytes
    thumbnail_bytes: bytes
    width: int
    height: int


def blob_root_for_store(store, explicit: Optional[str] = None) -> Optional[Path]:
    """Return a local sibling directory without creating it."""
    if explicit:
        return Path(explicit).expanduser().resolve()
    db_path = getattr(store, "path", None)
    if not db_path or db_path == ":memory:":
        return None
    resolved = Path(db_path).expanduser().resolve()
    return resolved.with_name(resolved.stem + ".assets")


def _read_source(source, max_bytes: int) -> bytes:
    limit = int(max_bytes)
    if limit <= 0:
        raise MediaError("media max_bytes must be positive")
    if isinstance(source, (bytes, bytearray)):
        raw = bytes(source)
    else:
        if not isinstance(source, (str, os.PathLike)):
            raise MediaError("photo source must be image bytes or an existing regular file")
        try:
            path = Path(source).expanduser().resolve(strict=True)
            if not path.is_file():
                raise MediaError(
                    "photo path must name an existing regular image file")
            if path.stat().st_size > limit:
                raise MediaError("photo exceeds the configured media size limit")
            raw = path.read_bytes()
        except MediaError:
            raise
        except (OSError, RuntimeError, ValueError) as exc:
            raise MediaError(
                "photo path must name an existing regular image file") from exc
    if len(raw) > limit:
        raise MediaError("photo exceeds the configured media size limit")
    if not raw:
        raise MediaError("photo source is empty")
    return raw


def _pillow():
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise MediaDependencyError(
            "Photo memory requires the fernme[media] optional extra (Pillow>=10)"
        ) from exc
    return Image, ImageOps


def _clean_mode(image, image_format: str):
    if image_format == "JPEG":
        return image.convert("RGB") if image.mode not in ("RGB", "L") else image
    if image.mode not in ("RGB", "RGBA", "L"):
        return image.convert("RGBA" if "transparency" in image.info else "RGB")
    return image


def _save_clean(image, image_format: str) -> bytes:
    output = BytesIO()
    if image_format == "JPEG":
        image.save(output, format="JPEG", quality=90, optimize=True)
    elif image_format == "PNG":
        image.save(output, format="PNG", optimize=True)
    else:
        image.save(output, format="WEBP", quality=90, method=4)
    return output.getvalue()


def _verify_no_exif(raw: bytes) -> None:
    Image, _ = _pillow()
    try:
        with Image.open(BytesIO(raw)) as image:
            image.load()
            if image.getexif() or image.info.get("exif"):
                raise MediaError("stored image still contains EXIF metadata")
    except MediaError:
        raise
    except Exception as exc:
        raise MediaError("stored image verification failed") from exc


def prepare_image(source, max_bytes: int = DEFAULT_MAX_BYTES,
                  thumbnail_max_px: int = DEFAULT_THUMBNAIL_MAX_PX) -> PreparedImage:
    """Validate, decode, strip metadata, and build a bounded thumbnail in memory."""
    raw = _read_source(source, max_bytes)
    Image, ImageOps = _pillow()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as probe:
                image_format = str(probe.format or "").upper()
                if image_format not in ALLOWED_FORMATS:
                    raise MediaError("photo must be JPEG, PNG, or WebP")
                probe.verify()
            with Image.open(BytesIO(raw)) as decoded:
                decoded.load()
                oriented = ImageOps.exif_transpose(decoded)
                clean = _clean_mode(oriented, image_format).copy()
                clean.info.clear()
    except MediaError:
        raise
    except Exception as exc:
        raise MediaError("photo content is not a valid supported image") from exc

    mime, extension = ALLOWED_FORMATS[image_format]
    clean_bytes = _save_clean(clean, image_format)
    _verify_no_exif(clean_bytes)

    max_px = int(thumbnail_max_px)
    if max_px <= 0:
        raise MediaError("media thumbnail_max_px must be positive")
    thumbnail = clean.copy()
    thumbnail.thumbnail((max_px, max_px), Image.Resampling.LANCZOS)
    thumbnail.info.clear()
    thumb_out = BytesIO()
    thumbnail.save(thumb_out, format="PNG", optimize=True)
    thumbnail_bytes = thumb_out.getvalue()
    _verify_no_exif(thumbnail_bytes)
    return PreparedImage(
        source_sha256=sha256(raw).hexdigest(),
        source_bytes=len(raw),
        mime=mime,
        extension=extension,
        clean_bytes=clean_bytes,
        thumbnail_bytes=thumbnail_bytes,
        width=int(clean.width),
        height=int(clean.height),
    )


def _owner_key(site: str, user: str) -> str:
    return sha256((str(site) + "\0" + str(user)).encode("utf-8")).hexdigest()[:24]


def persist_image(root: Path, site: str, user: str, asset_id: str,
                  prepared: PreparedImage) -> tuple[str, str]:
    """Write prepared bytes under generated paths and return absolute pointers."""
    root = Path(root).resolve()
    asset_dir = root / _owner_key(site, user) / asset_id
    try:
        asset_dir.mkdir(parents=True, exist_ok=False)
        image_path = asset_dir / ("original" + prepared.extension)
        thumbnail_path = asset_dir / "thumbnail.png"
        image_path.write_bytes(prepared.clean_bytes)
        thumbnail_path.write_bytes(prepared.thumbnail_bytes)
        return str(image_path.resolve()), str(thumbnail_path.resolve())
    except Exception as exc:
        if asset_dir.exists():
            shutil.rmtree(asset_dir, ignore_errors=True)
        raise MediaError("could not persist photo in the local blob store") from exc


def delete_media_files(root: Path, *uris: str) -> int:
    """Delete only regular files proven to be inside the configured blob root."""
    if root is None:
        raise MediaError("media blob directory is unavailable")
    resolved_root = Path(root).resolve()
    targets = []
    for uri in uris:
        if not uri:
            continue
        try:
            target = Path(uri).resolve(strict=True)
            target.relative_to(resolved_root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise MediaError("refusing to delete a media path outside the blob store") from exc
        if not target.is_file():
            raise MediaError("media pointer is not a regular file")
        targets.append(target)
    for target in targets:
        target.unlink()
    for target in targets:
        parent = target.parent
        while parent != resolved_root and parent.is_dir():
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
    return len(targets)
