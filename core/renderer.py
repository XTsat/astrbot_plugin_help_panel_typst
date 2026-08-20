import asyncio
import json
import os
import random
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.api.star import Star

from ..domain import InternalCFG, TypstPluginConfig
from ..utils import calculate_hash, get_image_dimensions, verify_image_header
from . import execute_render_task, RenderTask


class AsyncNullContext:  # 异步空上下文
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc_value, traceback):
        return None


class RenderResult:
    """渲染结果封装"""

    def __init__(self, images: list[str], temp_files: list[Path]):
        self.images = images
        self.temp_files = temp_files


class TypstRenderer:
    def __init__(
        self,
        star: Star,
        data_dir: Path,
        template_path: Path,
        font_dirs: list[Path],
        config: TypstPluginConfig,
    ):
        self.star = star
        self.data_dir = data_dir
        self.template_path = template_path
        self.font_dirs = font_dirs
        self.cfg = config
        self._compile_semaphore = asyncio.Semaphore(
            self.cfg.rendering.max_concurrent_tasks
        )
        self._cache_locks = {k: asyncio.Lock() for k in InternalCFG.CACHE_FILES.keys()}

        # 静态资源锁
        self._cache_locks = {k: asyncio.Lock() for k in InternalCFG.CACHE_FILES.keys()}

    def _get_config_snapshot(self) -> dict[str, Any]:
        """渲染配置的快照字典"""
        snapshot = {}
        for key in InternalCFG.CACHE_SENSITIVE_CONFIGS:
            # rendering 子配置
            if hasattr(self.cfg.rendering, key):
                val = getattr(self.cfg.rendering, key)
                snapshot[key] = val
            # 顶层 ignored_plugins
            elif hasattr(self.cfg, key):
                val = getattr(self.cfg, key)
                # set → list 并排序
                if isinstance(val, set):
                    snapshot[key] = sorted(list(val))
                else:
                    snapshot[key] = val

        # 提取“生效中”的外观配置
        if hasattr(self.cfg, "appearance"):
            snapshot["effective_fonts"] = self.cfg.appearance.get_active_font_order()
            snapshot["effective_colors"] = self.cfg.appearance.get_active_colors()

        # 头部背景图指纹 (路径 + 大小 + mtime), 背景图变更时缓存失效
        bg = self._resolve_background_image()
        if bg is not None:
            try:
                st = bg.stat()
                snapshot["background_image"] = {
                    "path": str(bg),
                    "size": st.st_size,
                    "mtime": st.st_mtime,
                }
            except OSError:
                snapshot["background_image"] = None
        else:
            snapshot["background_image"] = None

        return snapshot

    def _resolve_background_image(self) -> Path | None:
        """解析头部背景图

        优先级:
          1. header_background: 显式指定单个图片文件 (不使用随机)
          2. background_dir:    自定义背景目录, 只扫描该目录内的图片
          3. 默认背景目录:      数据目录下 backgrounds/ 子目录
        目录扫描规则: 该目录根下的图片文件 (排除 cache_/temp_ 前缀), 多张时按
        background_random 决定随机选一张或取文件名排序第一张。
        """
        # 1. 显式指定单个文件
        cfg_path = (self.cfg.header_background or "").strip()
        if cfg_path:
            p = Path(cfg_path)
            if p.is_file():
                return p
            logger.warning(f"[HelpTypst] 配置的背景图不存在: {cfg_path}, 回退目录扫描")

        # 2. 目录扫描 (自定义目录 → 默认 backgrounds 目录)
        scan_dirs: list[Path] = []
        custom_dir = (self.cfg.background_dir or "").strip()
        if custom_dir:
            scan_dirs.append(Path(custom_dir))
        scan_dirs.append(self.data_dir / InternalCFG.NAME_BACKGROUND_DIR)

        for scan_dir in scan_dirs:
            candidates = self._scan_background_dir(scan_dir)
            if not candidates:
                continue

            if len(candidates) > 1 and self.cfg.background_random:
                picked = random.choice(candidates)
                logger.debug(
                    f"[HelpTypst] 随机背景图: {picked.name} (共 {len(candidates)} 张)"
                )
                return picked

            if len(candidates) > 1:
                logger.warning(
                    f"[HelpTypst] 背景目录 {scan_dir} 检测到 {len(candidates)} 张图片, "
                    f"默认使用: {candidates[0].name} (可开启 background_random 随机选择)"
                )
            return candidates[0]

        return None

    def _scan_background_dir(self, scan_dir: Path) -> list[Path]:
        """扫描单个目录内的背景图候选 (仅目录根, 排除 cache_/temp_ 前缀)"""
        if not scan_dir.is_dir():
            return []
        candidates: list[Path] = []
        for ext in InternalCFG.BACKGROUND_IMAGE_EXTS:
            candidates.extend(scan_dir.glob(f"*{ext}"))
        candidates = [
            c
            for c in candidates
            if c.is_file()
            and not c.name.startswith(InternalCFG.BACKGROUND_IMAGE_EXCLUDE_PREFIXES)
        ]
        candidates.sort(key=lambda c: c.name)
        return candidates

    async def render(
        self,
        data_provider: Callable[[Path], int],
        mode: str,
        query: str | None = None,
    ) -> tuple[RenderResult | None, str]:
        """核心渲染流程"""
        # 1. 确定路径策略
        paths = self._resolve_paths(mode, query)
        json_path, img_path, kv_key = paths["json"], paths["img"], paths["kv_key"]
        is_temp, req_id = paths["is_temp"], paths["req_id"]

        # 2. 获取锁 (仅静态模式需要)
        lock = self._cache_locks.get(mode) if not is_temp else None

        try:
            async with lock or AsyncNullContext():
                # --- 1. 数据生成 ---
                try:
                    count = await asyncio.wait_for(
                        asyncio.to_thread(data_provider, json_path),
                        timeout=self.cfg.rendering.timeout_analysis,
                    )
                except asyncio.TimeoutError:
                    if is_temp and json_path.exists():
                        json_path.unlink(missing_ok=True)
                    return None, "数据分析超时，请检查插件列表是否过长"

                if count == 0:
                    if is_temp and json_path.exists():
                        json_path.unlink(missing_ok=True)
                    return None, "empty"

                # --- 2. 缓存校验 (仅静态) ---
                need_compile = True
                if not is_temp and json_path.exists():
                    # hash + config 双校验
                    need_compile = await self._check_cache(json_path, kv_key, img_path)

                if not need_compile:
                    cached_webps = self._find_cached_webps(img_path.stem)
                    if cached_webps:
                        return RenderResult(cached_webps, []), ""
                    else:
                        need_compile = True

                # --- 3. Typst 编译 ---
                if need_compile:
                    if not is_temp:
                        self._purge_old_cache(img_path.stem)

                    json_str = await asyncio.to_thread(
                        json_path.read_text, encoding="utf-8"
                    )

                    font_paths_str = [str(p) for p in self.font_dirs]

                    # 头部背景图: 解析路径/宽高比, 并计算沙箱 root (模板目录与数据目录的共同父目录)
                    bg_image = self._resolve_background_image()
                    bg_image_path: str | None = None
                    bg_aspect: float | None = None
                    root_dir: str | None = None
                    if bg_image is not None:
                        bg_image_path = str(bg_image)
                        dims = get_image_dimensions(bg_image)
                        if dims and dims[1] > 0:
                            bg_aspect = dims[0] / dims[1]
                        try:
                            root_dir = os.path.commonpath(
                                [str(self.template_path.parent), str(self.data_dir)]
                            )
                        except ValueError:
                            # 模板与数据目录无共同父目录 (如跨盘符), 放弃背景图
                            logger.warning(
                                "[HelpTypst] 模板目录与数据目录无共同父目录, 头部背景图不可用"
                            )
                            bg_image_path = None
                            bg_aspect = None
                            root_dir = None

                    # 构造 DTO
                    task = RenderTask(
                        template_path=str(self.template_path),
                        font_paths=font_paths_str,
                        json_str=json_str,
                        output_png_path=str(img_path),
                        output_dir=str(self.data_dir),
                        timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
                        query=query,
                        is_temp=is_temp,
                        req_id=req_id,
                        webp_limit=self.cfg.rendering.webp_limit,
                        split_height=self.cfg.rendering.split_height,
                        ppi=self.cfg.rendering.ppi,
                        bg_image_path=bg_image_path,
                        root_dir=root_dir,
                        bg_aspect=bg_aspect,
                        hero_header=self.cfg.hero_header,
                    )

                    # 调度执行
                    with ProcessPoolExecutor(max_workers=1) as temp_pool:
                        final_images = await asyncio.get_running_loop().run_in_executor(
                            temp_pool, execute_render_task, task
                        )

                    # 错误检查
                    if final_images and final_images[0].startswith("ERROR:"):
                        raise RuntimeError(final_images[0])

                    if not final_images:
                        return None, "渲染未生成图片文件"

                    # --- 4. 缓存写入 ---
                    if not is_temp and kv_key:
                        new_content_hash = calculate_hash(json_str)
                        current_config_snapshot = self._get_config_snapshot()

                        meta_data = {
                            "content_hash": new_content_hash,
                            "config": current_config_snapshot,
                        }

                        await self.star.put_kv_data(kv_key, meta_data)

                    # --- 5. 清理 ---
                    files_to_clean = []
                    if is_temp:
                        files_to_clean.extend([json_path, img_path])
                        files_to_clean.extend([Path(p) for p in final_images])

                    return RenderResult(final_images, files_to_clean), ""

        except Exception as e:
            logger.error(f"[HelpTypst] Render Error: {e}", exc_info=True)

            # 清理临时文件
            if is_temp:
                try:
                    if json_path.exists():
                        json_path.unlink()
                    if img_path.exists():
                        img_path.unlink()
                except Exception:
                    pass

            # 清理 KV 缓存
            if not is_temp and kv_key:
                try:
                    await self.star.delete_kv_data(kv_key)
                    logger.debug(f"[HelpTypst] 渲染异常，已清除缓存 Key: {kv_key}")
                except Exception as del_err:
                    # 这里吞掉删除异常，避免掩盖主异常 e
                    logger.warning(f"[HelpTypst] 清除缓存失败: {del_err}")

            return None, f"渲染过程出错: {str(e)}"

        return None, "未知错误"

    def _purge_old_cache(self, stem: str):
        """清理旧 WebP 缓存"""
        try:
            # 未切片的单图
            single_path = self.data_dir / f"{stem}.webp"
            if single_path.exists():
                single_path.unlink()

            # glob 匹配所有切片 (_part1.webp, _part2.webp ...)
            for p in self.data_dir.glob(f"{stem}_part*.webp"):
                p.unlink(missing_ok=True)

        except Exception as e:
            logger.warning(f"[HelpTypst] 清理旧缓存残留失败 {stem}: {e}")

    def _resolve_paths(self, mode: str, query: str | None) -> dict[str, Any]:
        """计算文件路径"""
        if query:
            uid = str(uuid.uuid4())
            return {
                "json": self.data_dir / f"temp_{uid}.json",
                "img": self.data_dir / f"temp_{uid}.png",
                "kv_key": None,
                "is_temp": True,
                "req_id": uid,
            }
        else:
            return {
                "json": self.data_dir
                / f"{InternalCFG.CACHE_FILES.get(mode, 'cache_unknown')}.json",
                "img": self.data_dir
                / f"{InternalCFG.CACHE_FILES.get(mode, 'cache_unknown')}.png",
                "kv_key": f"typst_cache_{mode}",
                "is_temp": False,
                "req_id": "static",
            }

    def _find_cached_webps(self, stem: str) -> list[str]:
        p1 = self.data_dir / f"{stem}.webp"
        if p1.exists():
            return [str(p1)]

        parts = sorted(self.data_dir.glob(f"{stem}_part*.webp"), key=lambda x: x.name)
        return [str(p) for p in parts] if parts else []

    async def _check_cache(self, json_path: Path, kv_key: str, img_path: Path) -> bool:
        """检查是否需要重新编译(AstrBot的简单KV存储)"""
        try:
            # 1. 计算当前 Hash
            json_content = await asyncio.to_thread(
                json_path.read_text, encoding="utf-8"
            )
            current_content_hash = calculate_hash(json_content)

            # 2. 读 KV 缓存
            if not kv_key:
                return True

            cached_meta = await self.star.get_kv_data(kv_key, default=None)

            if not cached_meta:
                return True  # 无缓存记录

            # 3. 解析缓存
            cached_content_hash = cached_meta.get("content_hash")
            cached_config = cached_meta.get("config", {})

            # 4. 当前配置快照
            current_config = self._get_config_snapshot()

            # 5. 图片完整性校验
            is_img_valid = False
            if img_path.exists():
                is_img_valid = await asyncio.to_thread(verify_image_header, img_path)

            # 6. 比对：内容一致 AND 配置一致 AND 图片有效
            if (
                cached_content_hash == current_content_hash
                and cached_config == current_config
                and is_img_valid
            ):
                logger.debug("[HelpTypst] 缓存命中 (Content + Config)。")
                return False  # 不需要编译

            logger.debug(
                f"[HelpTypst] 缓存失效。ConfigMatch={cached_config == current_config}"
            )
            return True

        except Exception as e:
            logger.warning(f"[HelpTypst] 缓存校验异常，强制重绘: {e}")
            return True
