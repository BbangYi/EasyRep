"""Decode a bounded still image and keep only normalized pixels."""

from io import BytesIO
from django.core.exceptions import ValidationError
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 24_000_000


def jpeg(image, bounds, budget):
    image = image.copy()
    image.thumbnail(bounds, Image.Resampling.LANCZOS)
    # A fresh canvas drops EXIF/GPS, comments and embedded profiles.
    clean = Image.new("RGB", image.size, "white")
    if image.mode == "RGBA":
        clean.paste(image, mask=image.getchannel("A"))
    else:
        clean.paste(image.convert("RGB"))
    for quality in (82, 72, 62):
        output = BytesIO()
        clean.save(output, "JPEG", quality=quality, optimize=True)
        if output.tell() <= budget:
            return output.getvalue(), clean.size
    raise ValidationError("사진을 최적화할 수 없습니다. 크기를 줄여 다시 선택하세요.")


def normalize(upload):
    if upload.size > MAX_UPLOAD_BYTES:
        raise ValidationError("5 MB 이하의 사진을 선택하세요.")
    try:
        with Image.open(upload, formats=["JPEG", "PNG", "WEBP"]) as image:
            if image.width * image.height > MAX_PIXELS:
                raise ValidationError("2,400만 화소 이하의 사진을 선택하세요.")
            if getattr(image, "n_frames", 1) != 1:
                raise ValidationError("움직이는 이미지 대신 정지 사진을 선택하세요.")
            image.verify()
        upload.seek(0)
        with Image.open(upload, formats=["JPEG", "PNG", "WEBP"]) as source:
            source.load()
            image = ImageOps.exif_transpose(source).convert("RGBA")
            content, (width, height) = jpeg(image, (1280, 1280), 512 * 1024)
            thumbnail, _ = jpeg(image, (320, 320), 48 * 1024)
        return {"content": content, "thumbnail": thumbnail, "width": width, "height": height}
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise ValidationError("사진을 읽을 수 없습니다. JPG, PNG 또는 WebP 사진을 선택하세요.")
