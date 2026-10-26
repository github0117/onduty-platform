import hashlib


def inspect_product_media(data: bytes, content_type: str) -> dict[str, object]:
    metadata: dict[str, object] = {
        "sha256": hashlib.sha256(data).hexdigest(),
        "analysis_status": "ANALYZED",
    }
    dimensions = _image_dimensions(data, content_type)
    if dimensions is None:
        metadata["analysis_status"] = "UNVERIFIED"
        return metadata
    width, height = dimensions
    metadata.update(
        {
            "width": width,
            "height": height,
            "aspect_ratio": round(width / height, 4) if height else 0.0,
            "orientation": "SQUARE"
            if width == height
            else "PORTRAIT"
            if height > width
            else "LANDSCAPE",
        }
    )
    if width >= 1024 and height >= 1024:
        quality_score = 0.95
        quality_status = "PASS"
    elif width >= 512 and height >= 512:
        quality_score = 0.85
        quality_status = "PASS"
    elif width >= 320 and height >= 320:
        quality_score = 0.72
        quality_status = "PASS"
    else:
        quality_score = 0.45
        quality_status = "LOW_RESOLUTION"
    if width == height:
        quality_score = min(1.0, quality_score + 0.05)
    metadata.update(
        {
            "quality_score": round(quality_score, 4),
            "quality_status": quality_status,
        }
    )
    return metadata


def _image_dimensions(data: bytes, content_type: str) -> tuple[int, int] | None:
    normalized = content_type.lower().split(";", 1)[0].strip()
    if normalized == "image/png":
        return _png_dimensions(data)
    if normalized == "image/jpeg":
        return _jpeg_dimensions(data)
    if normalized == "image/webp":
        return _webp_dimensions(data)
    return None


def _png_dimensions(data: bytes) -> tuple[int, int] | None:
    if (
        len(data) >= 24
        and data[:8] == b"\x89PNG\r\n\x1a\n"
        and data[12:16] == b"IHDR"
    ):
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    return None


def _jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    if not data.startswith(b"\xff\xd8"):
        return None
    sof_markers = {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        index += 2
        if marker in {0xD8, 0xD9}:
            continue
        if index + 2 > len(data):
            return None
        segment_length = int.from_bytes(data[index : index + 2], "big")
        if segment_length < 2 or index + segment_length > len(data):
            return None
        if marker in sof_markers and segment_length >= 7:
            height = int.from_bytes(data[index + 3 : index + 5], "big")
            width = int.from_bytes(data[index + 5 : index + 7], "big")
            return width, height
        index += segment_length
    return None


def _webp_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) < 30 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    chunk_type = data[12:16]
    chunk = data[20:]
    if chunk_type == b"VP8X" and len(chunk) >= 10:
        width = int.from_bytes(chunk[4:7], "little") + 1
        height = int.from_bytes(chunk[7:10], "little") + 1
        return width, height
    if chunk_type == b"VP8L" and len(chunk) >= 5 and chunk[0] == 0x2F:
        bits = int.from_bytes(chunk[1:5], "little")
        width = (bits & 0x3FFF) + 1
        height = ((bits >> 14) & 0x3FFF) + 1
        return width, height
    if chunk_type == b"VP8 " and len(chunk) >= 10 and chunk[3:6] == b"\x9d\x01\x2a":
        width = int.from_bytes(chunk[6:8], "little") & 0x3FFF
        height = int.from_bytes(chunk[8:10], "little") & 0x3FFF
        return width, height
    return None
