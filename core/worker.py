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

from ..domain import DefaultCFG, InternalCFG
from ..utils import process_image_to_output


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


def _collect_page_pngs(src: Path) -> list[Path]:
    """收集 Typst 分页渲染出的单页 PNG (`<stem>.pageN.png`), 按页码排序

    模板按内容高度自行分页, 每页都是一张完整的图 (自带头部与尾部),
    因此页码顺序就是发送顺序, 不能再按文件名做字典序排序 (page10 < page2)。
    """
    prefix = f"{src.stem}.page"
    pages: list[Path] = []
    for path in src.parent.glob(f"{prefix}*.png"):
        index = path.name[len(prefix) : -len(".png")]
        if index.isdigit():
            pages.append(path)
    return sorted(pages, key=lambda p: int(p.name[len(prefix) : -len(".png")]))


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
    # 静态模式下编译产物先落在临时 stem 上, 由渲染器成功后原子替换为正式缓存名;
    # 为空时沿用旧规则 (temp 用 temp_<req_id>, 静态用 png 文件名)
    output_stem: str | None = None
    webp_limit: int = DefaultCFG.LIMIT_WEBP
    split_height: int = DefaultCFG.LIMIT_SIDE
    output_format: str = DefaultCFG.OUTPUT_FORMAT
    ppi: float = DefaultCFG.LIMIT_PPI
    # 头部背景图 (可选): 绝对路径 + 沙箱 root
    bg_image_path: str | None = None
    root_dir: str | None = None
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
                ).replace("\\", "/")
                sys_inputs["bg_image"] = rel
            except ValueError:
                # 跨盘符等无法计算相对路径的情况 (Windows), 放弃背景图
                logger.warning(
                    f"[HelpTypst] 无法计算背景图相对路径: {task.bg_image_path}"
                )

        # Hero 品牌模式开关: sys_inputs 的值统一以字符串传递, 由模板集中解析成 bool
        sys_inputs["hero_header"] = "true" if task.hero_header else "false"

        # 品牌徽标: Typst 无法判断文件是否存在 (image 缺文件 = 硬编译错误),
        # 因此由 Python 侧探测并把结果以「相对路径 / 空串」告给模板, 缺图时跳过徽标
        logo_path = (
            Path(task.template_path).parent.parent
            / "resources"
            / "images"
            / "astrbot-logo-text.svg"
        )
        try:
            sys_inputs["logo_image"] = (
                os.path.relpath(logo_path, Path(task.template_path).parent).replace(
                    "\\", "/"
                )
                if logo_path.is_file()
                else ""
            )
        except ValueError:
            # 跨盘符等无法计算相对路径的情况: 当作缺图处理, 不影响整页
            sys_inputs["logo_image"] = ""

        # 单页高度上限 (pt): 由切片高度与清晰度换算, 模板据此决定是否分页 (0 = 不分页)
        sys_inputs["max_page_height"] = f"{task.split_height * 72.0 / max(1.0, float(task.ppi)):.2f}"

        # 3. 执行 Typst 编译: {p} 由 Typst 替换为页码, 长图在模板内按分类边界分页
        src_path = Path(task.output_png_path)
        typst.compile(
            task.template_path,
            output=f"{src_path.with_suffix('')}.page{{p}}.png",
            font_paths=task.font_paths,
            format="png",
            ppi=task.ppi,
            sys_inputs=sys_inputs,
            **compile_kwargs,
        )

        # 4. 调用图片处理
        # 计算文件名 stem
        final_stem = (
            task.output_stem
            or (f"temp_{task.req_id}" if task.is_temp else src_path.stem)
        )

        pages = _collect_page_pngs(src_path)
        try:
            if len(pages) <= 1:
                # 单页: 保留编译产物原名 (缓存靠它的 PNG 头做有效性校验)
                if not pages:
                    return []
                page = pages[0]
                outputs = process_image_to_output(
                    source_path=str(page),
                    output_dir=task.output_dir,
                    stem_name=final_stem,
                    webp_limit=task.webp_limit,
                    split_height=task.split_height,
                    output_format=task.output_format,
                )
                # PNG 输出且 stem 相同: 产物本身就是编译产物, 再把原页图搬过去反而会覆盖它
                if task.output_format == "png" and final_stem == src_path.stem:
                    page.unlink(missing_ok=True)
                else:
                    os.replace(page, src_path)
                return outputs

            # 多页: 每页本身就是完整面板, 直接按页码出图, 不再二次截切
            # 每页高度固定, 末页常只填了小半张 → 把页脚上提到正文之后,
            # 间距用「24pt 外沿 + 段间距」, 和正常分页页的正文↔页脚一致
            gap_pt = 24.0 + InternalCFG.FLOW_GAP_PT
            pad_px = max(1, int(round(gap_pt * float(task.ppi) / 72)))
            outputs: list[str] = []
            for index, page in enumerate(pages, start=1):
                outputs.extend(
                    process_image_to_output(
                        source_path=str(page),
                        output_dir=task.output_dir,
                        stem_name=f"{final_stem}_part{index}",
                        webp_limit=task.webp_limit,
                        split_height=task.split_height,
                        output_format=task.output_format,
                        trim_bottom=True,
                        pad_px=pad_px,
                    )
                )
            # 第一页保留为编译产物, 其余页 PNG 用完即删
            os.replace(pages[0], src_path)
            for page in pages[1:]:
                page.unlink(missing_ok=True)
            return outputs
        finally:
            # 异常/超时残留的单页 PNG 一并清掉
            for leftover in _collect_page_pngs(src_path):
                leftover.unlink(missing_ok=True)

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
