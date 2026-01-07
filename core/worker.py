import re
import traceback
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass
import typst
import gc
import platform
import ctypes

from ..utils import process_image_to_webp

def force_memory_release():
    # 1. Python 层
    gc.collect()

    # 2. glibc 层
    if platform.system() == "Linux":
        try:
            libc = ctypes.CDLL("libc.so.6")
            libc.malloc_trim(0)
        except Exception:
            pass

@dataclass
class RenderTask:
    template_path: str
    font_paths: List[str]
    json_str: str
    output_png_path: str
    output_dir: str
    timestamp: str
    query: Optional[str]
    is_temp: bool
    req_id: str
    webp_limit: int = 16383
    split_height: int = 16000
    ppi: float = 144.0

def execute_render_task(task: RenderTask) -> List[str]:
    """渲染子进程"""
    try:
        # 1. 准备参数
        sys_inputs = {
            "json_string": task.json_str,
            "timestamp": task.timestamp,
        }
        if task.query:
            sys_inputs["query_regex"] = re.escape(task.query)

        # 2. 执行 Typst 编译
        typst.compile(
            task.template_path,
            output=task.output_png_path,
            font_paths=task.font_paths,
            format="png", 
            ppi=task.ppi,
            sys_inputs=sys_inputs
        )

        # 3. 调用图片处理
        # 计算文件名 stem
        src_path = Path(task.output_png_path)
        final_stem = f"temp_{task.req_id}" if task.is_temp else src_path.stem

        return process_image_to_webp(
            source_path=task.output_png_path,
            output_dir=task.output_dir,
            stem_name=final_stem,
            webp_limit=task.webp_limit,
            split_height=task.split_height
        )

    except Exception:
        return [f"ERROR: {traceback.format_exc()}"]

    finally:
        # --- 4. 强制内存回收 ---
        force_memory_release()