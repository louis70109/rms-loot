from io import BytesIO

import pytest
from PIL import Image

from images import MAX_SIDE, TARGET_BYTES, ImageRejected, compress_image


def _png_bytes(img, fmt="PNG", **kwargs):
    buf = BytesIO()
    img.save(buf, format=fmt, **kwargs)
    return buf.getvalue()


def _gradient_photo(width=3000, height=2000):
    # 平滑漸層 + 輕微雜訊，接近一張拍照的大小與壓縮特性
    base = Image.linear_gradient("L").resize((width, height)).convert("RGB")
    noise = Image.effect_noise((width, height), 8).convert("RGB")
    return Image.blend(base, noise, 0.1)


def test_large_photo_is_shrunk_to_jpeg_within_target():
    raw = _png_bytes(_gradient_photo())
    out = compress_image(raw)

    assert len(out) < len(raw)
    assert len(out) <= TARGET_BYTES
    img = Image.open(BytesIO(out))
    assert img.format == "JPEG"
    assert max(img.size) <= MAX_SIDE


def test_small_image_keeps_its_dimensions():
    raw = _png_bytes(Image.new("RGB", (320, 200), (30, 120, 200)))
    img = Image.open(BytesIO(compress_image(raw)))
    assert img.size == (320, 200)


def test_non_image_bytes_are_rejected():
    with pytest.raises(ImageRejected):
        compress_image(b"this is a text file, not an image")


def test_truncated_image_is_rejected():
    raw = _png_bytes(_gradient_photo(400, 300))
    with pytest.raises(ImageRejected):
        compress_image(raw[: len(raw) // 3])


def test_transparent_png_gets_white_background():
    img = Image.new("RGBA", (200, 200), (0, 0, 0, 0))  # 全透明
    out = Image.open(BytesIO(compress_image(_png_bytes(img))))
    assert out.mode == "RGB"
    assert out.getpixel((10, 10)) == (255, 255, 255)


def test_exif_orientation_is_applied_and_metadata_dropped():
    img = Image.new("RGB", (200, 100), (200, 50, 50))
    exif = Image.Exif()
    exif[0x0112] = 6  # 手機直拍：需要旋轉 90 度
    raw = _png_bytes(img, fmt="JPEG", exif=exif.tobytes())

    out = Image.open(BytesIO(compress_image(raw)))
    assert out.size == (100, 200)
    assert len(out.getexif()) == 0  # GPS 等資訊不應留在上傳後的檔案裡
