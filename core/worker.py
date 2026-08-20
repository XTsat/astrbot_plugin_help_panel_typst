import ctypes
import gc
import os
import platform
import re
import traceback
from dataclasses import dataclass
from pathlib import Path

import typst
from astrbot.api import logger

from ..domain import DefaultCFG
from ..utils import process_image_to_webp


def force_memory_release():
    # Python 层
    gc.collect()

    # glibc 层
    if platform.system() == "Linux":
        try:
            libc = ctypes.CDLL("libc.so.6")
            libc.malloc_trim(0)
        except Exception:
            pass


@dataclass
class RenderTask:
    template_path: str
    font_paths: list[str]
    json_str: str
    output_png_path: str
    output_dir: str
    timestamp: str
    query: str | None
    is_temp: bool
    req_id: str
    webp_limit: int = DefaultCFG.LIMIT_WEBP
    split_height: int = DefaultCFG.LIMIT_SIDE
    ppi: float = DefaultCFG.LIMIT_PPI
    # 头部背景图 (可选): 绝对路径 + 沙箱 root + 宽高比
    bg_image_path: str | None = None
    root_dir: str | None = None
    bg_aspect: float | None = None
    # Hero 品牌模式开关 (默认开启)
    hero_header: bool = True


def execute_render_task(task: RenderTask) -> list[str]:
    """渲染子进程"""
    try:
        # 1. 准备参数
        sys_inputs = {
            "json_string": task.json_str,
            "timestamp": task.timestamp,
        }
        if task.query:
            sys_inputs["query_regex"] = re.escape(task.query)

        # 2. 背景图注入: 路径相对模板目录, 便于 Typst 在 root 内解析
        compile_kwargs: dict = {}
        if task.root_dir:
            compile_kwargs["root"] = task.root_dir

        if task.bg_image_path:
            try:
                rel = os.path.relpath(
                    task.bg_image_path, Path(task.template_path).parent
                )
                sys_inputs["bg_image"] = rel
            except ValueError:
                # 跨盘符等无法计算相对路径的情况 (Windows), 放弃背景图
                logger.warning(
                    f"[HelpTypst] 无法计算背景图相对路径: {task.bg_image_path}"
                )
            if task.bg_aspect:
                sys_inputs["bg_aspect"] = f"{task.bg_aspect:.6f}"

        # Hero 品牌模式开关注入模板
        sys_inputs["hero_header"] = "true" if task.hero_header else "false"

        # 3. 执行 Typst 编译
        typst.compile(
            task.template_path,
            output=task.output_png_path,
            font_paths=task.font_paths,
            format="png",
            ppi=task.ppi,
            sys_inputs=sys_inputs,
            **compile_kwargs,
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
            split_height=task.split_height,
        )

    except typst.TypstError as e:
        # 完整回显 typst 诊断 (message/diagnostic/hints/trace), 便于直接定位
        parts = [f"Typst 编译错误: {getattr(e, 'message', None) or str(e)}"]
        diag = getattr(e, "diagnostic", "")
        if diag:
            parts.append(f"诊断: {diag}")
        hints = getattr(e, "hints", None)
        if hints:
            parts.append(f"提示: {'; '.join(hints)}")
        trace = getattr(e, "trace", None)
        if trace:
            parts.append(f"位置: {' | '.join(str(t) for t in trace)}")
        return [f"ERROR: {chr(10).join(parts)}"]

    except Exception:
        return [f"ERROR: {traceback.format_exc()}"]

    finally:
        # 4. 强制内存回收
        force_memory_release()
