import math
from pathlib import Path
from typing import List
from PIL import Image

from ..domain import DefaultCFG

def verify_image_header(path: Path) -> bool:
    """简单的图片完整性校验"""
    try:
        with Image.open(path) as img:
            img.verify()
        return True
    except Exception:
        return False

def process_image_to_webp(
    source_path: str, 
    output_dir: str, 
    stem_name: str, 
    webp_limit: int, 
    split_height: int
) -> List[str]:
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
                    
                    chunk_path = out_dir_obj / f"{stem_name}_part{i+1}.webp"
                    chunk.save(chunk_path, "WEBP", quality=80, method=6)
                    images.append(str(chunk_path))
                    
    except Exception as e:
        # 抛出异常让上层捕获
        raise RuntimeError(f"图片处理失败: {e}")

    return images