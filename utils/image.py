import math
from pathlib import Path

from PIL import Image

from ..domain import DefaultCFG, InternalCFG

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


def _row_uniform(rgb: Image.Image, width: int, row: int, tolerance: int) -> bool:
    extrema = rgb.crop((0, row, width, row + 1)).getextrema()
    return all(channel_max - channel_min <= tolerance for channel_min, channel_max in extrema)


def _band_uniform(rgb: Image.Image, width: int, top: int, bottom: int, tolerance: int) -> bool:
    extrema = rgb.crop((0, top, width, bottom)).getextrema()
    return all(channel_max - channel_min <= tolerance for channel_min, channel_max in extrema)


def _trim_page_blank(img: Image.Image, pad_px: int, tolerance: int = 2) -> Image.Image:
    """去掉分页产物「正文与页脚之间」的整段空白, 把页脚上提到正文之后

    分页的页面高度固定, 末页常常只填了小半张: 空白出现在正文结束后、页脚之前,
    单纯裁底部只会裁到页脚以下那点边距。这里把图拆成「正文 / 页脚」两段重新拼接。
    页脚在每页内容一致, 因此按行扫描定位即可, 不需要模板侧再输出高度。
    """
    rgb = img.convert("RGB")
    width, height = rgb.size
    if height < 32:
        return img
    step = 16

    # 1) 页脚底部: 自下而上第一条有内容的行
    row = height - 1
    while row > 0 and _row_uniform(rgb, width, row, tolerance):
        row -= 1
    footer_bottom = row + 1  # 页脚墨迹底部 (其下是页面下边距)

    # 2) 页脚顶部: 继续向上, 遇到连续空白 (页脚上方的大段间隙) 即为页脚结束
    footer_top = footer_bottom
    scan = footer_bottom
    found_footer_top = False
    while scan > 0:
        top = max(0, scan - step)
        if _band_uniform(rgb, width, top, scan, tolerance):
            footer_top = scan
            found_footer_top = True
            break
        scan = top
    if not found_footer_top:
        return img

    # 3) 正文底部: 从页脚顶部继续向上, 第一段非空白即正文末尾
    content_bottom = 0
    scan = footer_top
    while scan > 0:
        top = max(0, scan - step)
        if not _band_uniform(rgb, width, top, scan, tolerance):
            for candidate in range(scan, top, -1):
                if not _row_uniform(rgb, width, candidate - 1, tolerance):
                    content_bottom = candidate
                    break
            else:
                content_bottom = top
            break
        scan = top

    if content_bottom <= 0 or footer_top - content_bottom < step:
        # 正文已经贴着页脚, 没有可压缩的空白
        return img

    background = rgb.getpixel((width // 2, height - 1))
    body = rgb.crop((0, 0, width, content_bottom))
    # 页脚连同它下面的页面下边距整体搬走, 这样底部留白与分页页保持一致,
    # 且新高度必定不超过原页高 (否则等于白裁)
    bottom_block = rgb.crop((0, footer_top, width, height))

    new_height = body.height + pad_px + bottom_block.height
    if new_height >= height:
        return img
    merged = Image.new("RGB", (width, new_height), background)
    merged.paste(body, (0, 0))
    merged.paste(bottom_block, (0, body.height + pad_px))
    return merged
def _save_rendered(img: Image.Image, path: Path, output_format: str) -> None:
    """按所选格式保存: 面板是大色块 + 文字, 各格式的取舍点不同"""
    if output_format == "png":
        # 无损, 体积约为 WebP 的 5~6 倍, 换来原图级别的小字锐度
        img.save(path, "PNG", optimize=True, compress_level=6)
    elif output_format == "jpeg":
        # 不支持透明, 需要先转 RGB; subsampling=0 关闭色度抽样, 避免中文小字出现彩边
        img.convert("RGB").save(path, "JPEG", quality=92, optimize=True, subsampling=0)
    else:
        img.save(path, "WEBP", quality=80, method=6)


def process_image_to_output(
    source_path: str,
    output_dir: str,
    stem_name: str,
    webp_limit: int,
    split_height: int,
    output_format: str = DefaultCFG.OUTPUT_FORMAT,
    trim_bottom: bool = False,
    pad_px: int = 0,
) -> list[str]:
    """把 Typst 产出的 PNG 转成发送格式, 超长时按高度切片

    单张高度上限与切片高度都要先按所选格式的边长上限收敛:
    WebP 硬限制 16383, PNG/JPEG 上限更大但仍有实用上限。
    """
    images = []
    src_path_obj = Path(source_path)
    out_dir_obj = Path(output_dir)

    if not src_path_obj.exists():
        return []
    try:
        fmt = output_format if output_format in InternalCFG.FORMAT_EXT else DefaultCFG.OUTPUT_FORMAT
        ext = InternalCFG.FORMAT_EXT[fmt]
        max_side = InternalCFG.FORMAT_MAX_SIDE[fmt]
        # 与 domain/config 的收敛区间保持一致: 非法值回落到下限,
        # split_height 为 0 会在下面的除法里抛零除错误
        limit = max(DefaultCFG.MIN_WEBP_LIMIT, int(webp_limit))
        limit = min(limit, max_side)
        step = max(DefaultCFG.MIN_SPLIT_HEIGHT, int(split_height))
        step = min(step, max_side)
        with Image.open(src_path_obj) as img:
            if trim_bottom:
                # 分页产物: 每页高度固定, 末页常有大片空白
                img = _trim_page_blank(img, pad_px)
            if img.height <= limit:
                # 不切分
                out_path = out_dir_obj / f"{stem_name}{ext}"
                _save_rendered(img, out_path, fmt)
                images.append(str(out_path))
            else:
                # 切分: 每片高度不超过所选格式的上限
                width, total_height = img.size
                chunks = math.ceil(total_height / step)
                for i in range(chunks):
                    top = i * step
                    bottom = min((i + 1) * step, total_height)

                    box = (0, top, width, bottom)
                    chunk = img.crop(box)

                    chunk_path = out_dir_obj / f"{stem_name}_part{i + 1}{ext}"
                    _save_rendered(chunk, chunk_path, fmt)
                    images.append(str(chunk_path))

    except Exception as e:
        # 抛出异常让上层捕获
        raise RuntimeError(f"图片处理失败 ({src_path_obj.name}): {e}")

    return images
