import math
from pathlib import Path

from PIL import Image

# PIL 格式名 → 合法的文件扩展名集合 (全小写, 不含点)
_FORMAT_EXTENSIONS: dict[str, set[str]] = {
    "JPEG": {"jpg", "jpeg"},
    "PNG": {"png"},
    "WEBP": {"webp"},
    "BMP": {"bmp"},
    "GIF": {"gif"},
    "TIFF": {"tif", "tiff"},
}


def verify_image_header(path: Path) -> bool:
    """简单的图片完整性校验"""
    try:
        with Image.open(path) as img:
            img.verify()
        return True
    except Exception:
        return False


def verify_image_format_matches_extension(path: Path) -> bool:
    """检查图片的实际格式是否与文件扩展名一致

    Typst 根据文件扩展名决定解码器（如 .jpg → JPEG 解码器），
    如果扩展名与实际格式不匹配（如实际为 WebP 但扩展名为 .jpg），
    Typst 会解码失败。此函数用 PIL 检测实际格式并比对扩展名。
    """
    try:
        with Image.open(path) as img:
            # img.format 是 PIL 检测到的真实格式 (如 "JPEG", "WEBP", "PNG")
            actual_format = img.format
            if actual_format is None:
                return False  # 无法检测格式

            expected_exts = _FORMAT_EXTENSIONS.get(actual_format)
            if expected_exts is None:
                # 未知格式 (PIL 认识但不在此映射表中), 保守地放行
                return True

            ext = path.suffix.lower().lstrip(".")
            return ext in expected_exts
    except Exception:
        return False


def get_image_dimensions(path: Path) -> tuple[int, int] | None:
    """读取图片宽高 (px)。读取失败返回 None"""
    try:
        with Image.open(path) as img:
            return img.size
    except Exception:
        return None


def process_image_to_webp(
    source_path: str,
    output_dir: str,
    stem_name: str,
    webp_limit: int,
    split_height: int,
) -> list[str]:
    """核心图片处理逻辑"""
    images = []
    src_path_obj = Path(source_path)
    out_dir_obj = Path(output_dir)

    if not src_path_obj.exists():
        return []
    try:
        with Image.open(src_path_obj) as img:
            if img.height <= webp_limit:
                # 不切分
                webp_path = out_dir_obj / f"{stem_name}.webp"
                img.save(webp_path, "WEBP", quality=80, method=6)
                images.append(str(webp_path))
            else:
                # 切分
                width, total_height = img.size
                chunks = math.ceil(total_height / split_height)
                for i in range(chunks):
                    top = i * split_height
                    bottom = min((i + 1) * split_height, total_height)

                    box = (0, top, width, bottom)
                    chunk = img.crop(box)

                    chunk_path = out_dir_obj / f"{stem_name}_part{i + 1}.webp"
                    chunk.save(chunk_path, "WEBP", quality=80, method=6)
                    images.append(str(chunk_path))

    except Exception as e:
        # 抛出异常让上层捕获
        raise RuntimeError(f"图片处理失败: {e}")

    return images
