"""圖片壓縮：上傳的截圖或照片先縮圖、轉成 JPEG，省下 volume 空間。

只負責把 bytes 變小，不碰資料庫或路由；之後的上傳功能直接呼叫 compress_image。
"""

from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_SIDE = 1600           # 長邊上限（像素）
TARGET_BYTES = 400_000    # 目標大小，超過就降低畫質重試
QUALITIES = (80, 70, 60, 50)
MAX_INPUT_PIXELS = 40_000_000  # 防止解壓炸彈（約 6000x6600）


class ImageRejected(ValueError):
    """不是圖片，或圖片太大。"""


def compress_image(data: bytes) -> bytes:
    """回傳壓縮後的 JPEG bytes。非圖片或超過像素上限會丟出 ImageRejected。"""
    Image.MAX_IMAGE_PIXELS = MAX_INPUT_PIXELS
    try:
        img = Image.open(BytesIO(data))
        img.load()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
        raise ImageRejected("不是可以讀取的圖片") from exc

    # 依 EXIF 轉正（手機直拍常見的旋轉問題），再丟掉 EXIF 以免夾帶 GPS 等資訊
    img = ImageOps.exif_transpose(img)
    img.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)

    # JPEG 沒有透明度；透明的 PNG 鋪上白底
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        base = Image.new("RGB", rgba.size, (255, 255, 255))
        base.paste(rgba, mask=rgba.split()[-1])
        img = base
    elif img.mode != "RGB":
        img = img.convert("RGB")

    out = b""
    for quality in QUALITIES:
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True, progressive=True)
        out = buf.getvalue()
        if len(out) <= TARGET_BYTES:
            break
    return out
