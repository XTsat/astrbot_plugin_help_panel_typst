import asyncio
import json
import os
import random
import re
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.api.star import Star

from ..domain import InternalCFG, TypstPluginConfig
from ..utils import (
    calculate_hash,
    verify_image_format_matches_extension,
    verify_image_header,
)
from . import execute_render_task, RenderTask


def _part_index(path: Path) -> int:
    """按 `_partN` 里的 N 排序

    字典序会把 `_part10` 排到 `_part2` 之前, 长图发送顺序就乱了。
    """
    match = re.search(r"_part(\d+)\.webp$", path.name)
    return int(match.group(1)) if match else 0


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
        # 全局编译并发上限: 配置值可能被手工改成 0 或负数, 收敛到至少 1 避免永久阻塞
        self._compile_semaphore = asyncio.Semaphore(
            max(1, int(self.cfg.rendering.max_concurrent_tasks))
        )
        # 静态资源锁 (每个静态 mode 一把, 避免同模式重复编译)
        self._cache_locks = {k: asyncio.Lock() for k in InternalCFG.CACHE_FILES.keys()}

    def _get_config_snapshot(self, bg_image: Path | None = None) -> dict[str, Any]:
        """渲染配置的快照字典

        背景图由调用方以参数显式传入, 不使用实例属性: 同一实例上的并发请求会互相
        覆盖背景图, 导致快照指纹与实际编译的图片不是同一张 (缓存命中即错图)。
        """
        snapshot: dict[str, Any] = {}
        for key in InternalCFG.CACHE_SENSITIVE_CONFIGS:
            # rendering 子配置
            if hasattr(self.cfg.rendering, key):
                val = getattr(self.cfg.rendering, key)
                snapshot[key] = val
            # 顶层 ignored_plugins
            elif hasattr(self.cfg, key):
                val = getattr(self.cfg, key)
                # set → list 并排序 (统一转 str: 配置被手工改成混合类型时不能让快照抛 TypeError)
                if isinstance(val, set):
                    snapshot[key] = sorted(str(v) for v in val)
                # 分类规则 (dataclass 不可直接 JSON 序列化, 转为纯结构)
                elif key == "category":
                    snapshot[key] = val.to_plain()
                else:
                    snapshot[key] = val

        # 提取“生效中”的外观配置
        if hasattr(self.cfg, "appearance"):
            snapshot["effective_fonts"] = self.cfg.appearance.get_active_font_order()
            snapshot["effective_colors"] = self.cfg.appearance.get_active_colors()

        # 头部背景图指纹 (路径 + 大小 + mtime), 背景图变更时缓存失效
        if bg_image is not None:
            try:
                st = bg_image.stat()
                snapshot["background_image"] = {
                    "path": str(bg_image),
                    "size": st.st_size,
                    "mtime": st.st_mtime,
                }
            except OSError:
                snapshot["background_image"] = None
        else:
            snapshot["background_image"] = None

        # 模板指纹: 模板改动不参与内容 hash, 只能靠快照失效, 否则升级后仍返回旧布局的缓存图
        try:
            tpl_stat = self.template_path.stat()
            snapshot["template"] = {
                "path": str(self.template_path),
                "size": tpl_stat.st_size,
                "mtime": tpl_stat.st_mtime,
            }
        except OSError:
            snapshot["template"] = None

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
                if p.suffix.lower() not in InternalCFG.BACKGROUND_IMAGE_EXTS:
                    # Typst 只能解码白名单内的栅格格式, 放行会让整页编译失败
                    logger.warning(
                        f"[HelpTypst] 配置的背景图格式不受支持: {cfg_path}, "
                        f"仅支持 {', '.join(InternalCFG.BACKGROUND_IMAGE_EXTS)}, 回退目录扫描"
                    )
                elif not verify_image_header(p):
                    logger.warning(
                        f"[HelpTypst] 配置的背景图无法打开: {cfg_path}, 回退目录扫描"
                    )
                elif not verify_image_format_matches_extension(p):
                    logger.warning(
                        f"[HelpTypst] 配置的背景图格式与扩展名不匹配: {cfg_path}, 回退目录扫描"
                    )
                else:
                    return p
            else:
                logger.warning(
                    f"[HelpTypst] 配置的背景图不存在: {cfg_path}, 回退目录扫描"
                )

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
        # 用 suffix 小写比较而非 glob: Linux 文件系统区分大小写, *.PNG / *.JPG
        # 用 glob("*{ext}") 会漏掉
        try:
            candidates: list[Path] = [
                p
                for p in scan_dir.iterdir()
                if p.suffix.lower() in InternalCFG.BACKGROUND_IMAGE_EXTS
            ]
        except OSError as e:
            logger.warning(f"[HelpTypst] 背景目录无法读取 {scan_dir}: {e}")
            return []
        # 先筛选出有效的基本候选 (文件存在 + 非排除前缀)
        valid_basic = [
            c
            for c in candidates
            if c.is_file()
            and not c.name.startswith(InternalCFG.BACKGROUND_IMAGE_EXCLUDE_PREFIXES)
        ]
        # 再进一步过滤格式不匹配或无法打开的图片
        candidates = [
            c
            for c in valid_basic
            if verify_image_header(c) and verify_image_format_matches_extension(c)
        ]
        skipped = len(valid_basic) - len(candidates)
        if skipped > 0:
            logger.warning(
                f"[HelpTypst] 背景目录 {scan_dir} 中有 {skipped} 张图片格式不匹配或无法打开, 已跳过"
            )
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

        # 背景图在本批次开始时只解析一次, 并用局部变量贯穿「快照」与「编译」:
        # 写实例属性会被并发请求覆盖, 导致 KV 里记录的指纹与实际编译的图片不是同一张
        bg_image = self._resolve_background_image()

        # 静态模式的编译产物先落在临时 stem 上, 成功后再原子替换到正式缓存名:
        # 直接写正式名 / 编译前先删旧文件, 会让正在发送上一张图的请求读到被删掉的文件
        compile_stem = f"temp_{uuid.uuid4().hex}"
        compile_png = self.data_dir / f"{compile_stem}.png"
        output_png = img_path if is_temp else compile_png
        # 本次请求的临时产物 stem (取消/异常时按它清理)
        artifact_stem = img_path.stem if is_temp else compile_stem

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
                    need_compile = await self._check_cache(
                        json_path, kv_key, img_path, bg_image
                    )

                if not need_compile:
                    cached_webps = self._find_cached_webps(img_path.stem)
                    if cached_webps:
                        return RenderResult(cached_webps, []), ""
                    else:
                        need_compile = True

                # --- 3. Typst 编译 ---
                if need_compile:
                    json_str = await asyncio.to_thread(
                        json_path.read_text, encoding="utf-8"
                    )

                    # 编译时字体目录 = 项目目录 + 系统字体库 (由 main 注入的搜索路径,
                    # 与扫描保持一致, 否则系统内置字体虽被扫描进选项, 编译时却未加载而不生效)
                    font_paths_str = [str(p) for p in self.font_dirs]

                    # 头部背景图: 使用批次开始时已解析的背景图 (确保 random 只选一次)
                    bg_image_path: str | None = str(bg_image) if bg_image is not None else None
                    # 插件根目录: root 必须覆盖它, 否则模板里的 ../resources 徽标读不到
                    plugin_root = str(self.template_path.parent.parent)
                    root_paths = [
                        str(self.template_path.parent),
                        str(self.data_dir),
                        plugin_root,
                    ]
                    if bg_image_path is not None:
                        # 背景图放在数据目录之外 (自定义 background_dir / header_background)
                        # 时, 只按「模板 + 数据目录」算 root 会让 Typst 拒绝读取 → 整页编译失败
                        root_paths.append(bg_image_path)
                    try:
                        root_dir: str | None = os.path.commonpath(root_paths)
                    except ValueError:
                        # 跨盘符等无共同父目录的情况: 放弃背景图, 而不是放弃整页;
                        # root 回落到插件目录, 保证模板与内置资源仍可读取
                        if bg_image_path is not None:
                            logger.warning(
                                "[HelpTypst] 背景图与模板/数据目录无共同父目录, 头部背景图不可用"
                            )
                        bg_image_path = None
                        root_dir = plugin_root

                    # 构造 DTO
                    task = RenderTask(
                        template_path=str(self.template_path),
                        font_paths=font_paths_str,
                        json_str=json_str,
                        output_png_path=str(output_png),
                        output_dir=str(self.data_dir),
                        output_stem=None if is_temp else compile_stem,
                        timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
                        query=query,
                        is_temp=is_temp,
                        req_id=req_id,
                        webp_limit=self.cfg.rendering.webp_limit,
                        split_height=self.cfg.rendering.split_height,
                        ppi=self.cfg.rendering.ppi,
                        bg_image_path=bg_image_path,
                        root_dir=root_dir,
                        hero_header=self.cfg.hero_header,
                    )

                    # 调度执行: 全局并发上限 + 编译超时, 避免一次挂死永久持有 mode 锁
                    pool = ProcessPoolExecutor(max_workers=1)
                    try:
                        async with self._compile_semaphore:
                            final_images = await asyncio.wait_for(
                                asyncio.get_running_loop().run_in_executor(
                                    pool, execute_render_task, task
                                ),
                                timeout=max(
                                    1.0, float(self.cfg.rendering.timeout_compile)
                                ),
                            )
                    except asyncio.TimeoutError:
                        logger.warning(
                            f"[HelpTypst] 编译超时 (>={self.cfg.rendering.timeout_compile}s), "
                            f"已放弃本次渲染: mode={mode}"
                        )
                        # 子进程可能仍在写文件, 延迟再清一次它迟到的产物
                        self._schedule_artifact_cleanup(artifact_stem)
                        if is_temp:
                            json_path.unlink(missing_ok=True)
                        return None, "渲染超时，请稍后重试或减少插件数量"
                    finally:
                        # wait=False: 超时/取消时不能阻塞事件循环等待子进程退出
                        pool.shutdown(wait=False, cancel_futures=True)

                    # 错误检查: 子进程把 typst 诊断/内部路径都塞在 ERROR: 后面,
                    # 这些只适合进日志; 回给群里的一律是简短提示, 避免泄露部署路径
                    if final_images and final_images[0].startswith("ERROR:"):
                        detail = final_images[0][len("ERROR:") :].strip()
                        logger.error(f"[HelpTypst] Typst 编译失败: {detail}")
                        raise RuntimeError("Typst 编译失败，请检查模板与字体配置（详见日志）")

                    if not final_images:
                        return None, "渲染未生成图片文件"

                    # 静态模式: 原子替换到正式缓存名, 不删除在途请求正在发送的图片
                    if not is_temp:
                        final_images = await asyncio.to_thread(
                            self._commit_cache_images,
                            img_path,
                            compile_png,
                            final_images,
                            compile_stem,
                        )

                    # --- 4. 缓存写入 ---
                    if not is_temp and kv_key:
                        new_content_hash = calculate_hash(json_str)
                        current_config_snapshot = self._get_config_snapshot(bg_image)

                        meta_data = {
                            "content_hash": new_content_hash,
                            "config": current_config_snapshot,
                        }

                        await self.star.put_kv_data(kv_key, meta_data)

                    # --- 5. 清理 ---
                    files_to_clean: list[Path] = []
                    if is_temp:
                        files_to_clean.extend([json_path, img_path])
                        files_to_clean.extend([Path(p) for p in final_images])

                    return RenderResult(final_images, files_to_clean), ""

        except asyncio.CancelledError:
            # 取消同样要清理: 否则 temp_* 会一直堆到下次插件卸载
            logger.warning("[HelpTypst] 渲染被取消, 清理本次临时产物")
            if is_temp:
                try:
                    json_path.unlink(missing_ok=True)
                except OSError as clean_err:
                    # 清理失败不该掩盖真正的取消原因 (磁盘只读等), 记 warning 后继续抛
                    logger.warning(f"[HelpTypst] 清理临时 JSON 失败: {clean_err}")
            self._discard_artifacts(artifact_stem)
            raise

        except Exception as e:
            logger.error(f"[HelpTypst] Render Error: {e}", exc_info=True)

            # 清理临时文件 (json / 编译中间产物)
            if is_temp:
                try:
                    json_path.unlink(missing_ok=True)
                except OSError as clean_err:
                    # 同 CancelledError 分支: 清理失败只告警, 不覆盖主异常 e
                    logger.warning(f"[HelpTypst] 清理临时 JSON 失败: {clean_err}")
            self._discard_artifacts(artifact_stem)

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

    def _commit_cache_images(
        self,
        cache_png: Path,
        compile_png: Path,
        produced_webps: list[str],
        compile_stem: str,
    ) -> list[str]:
        """把临时 stem 上的编译产物原子替换为正式缓存文件

        os.replace 是原子操作: 正式缓存名在任何时刻都指向一份完整文件, 不会出现
        「文件被删掉」的窗口, 并发请求正在发送上一张图时也不会读不到文件。
        """
        committed: list[Path] = []
        os.replace(compile_png, cache_png)
        for produced in produced_webps:
            suffix = Path(produced).name[len(compile_stem) :]
            target = self.data_dir / f"{cache_png.stem}{suffix}"
            os.replace(produced, target)
            committed.append(target)

        # 单图 ↔ 分片 或 分片数变少时, 清掉本次没有产出的旧分片
        self._discard_stale_webps(cache_png.stem, committed)
        self._discard_artifacts(compile_stem)
        return [str(p) for p in committed]

    def _discard_stale_webps(self, stem: str, keep: list[Path]) -> None:
        """删除某个静态 mode 下本次未产出的旧 WebP (含旧分片)

        只匹配本 mode 自己的文件名: cache_menu_command 与 cache_menu_command_detail
        互为前缀, 用 glob(f"{stem}*.webp") 会误删另一个模式的缓存。
        """
        keep_names = {p.name for p in keep}
        part_pattern = re.compile(rf"^{re.escape(stem)}_part\d+\.webp$")
        try:
            entries = list(self.data_dir.iterdir())
        except OSError as e:
            logger.warning(f"[HelpTypst] 清理旧缓存失败 {stem}: {e}")
            return
        for entry in entries:
            if entry.name in keep_names:
                continue
            if entry.name != f"{stem}.webp" and not part_pattern.match(entry.name):
                continue
            try:
                entry.unlink(missing_ok=True)
            except OSError as e:
                logger.warning(f"[HelpTypst] 清理旧缓存文件失败 {entry}: {e}")

    def _discard_artifacts(self, stem: str) -> None:
        """尽力删除某个 stem 的编译产物 (png / webp / 分片)"""
        leftovers = [self.data_dir / f"{stem}.png", self.data_dir / f"{stem}.webp"]
        leftovers.extend(self.data_dir.glob(f"{stem}_part*.webp"))
        for path in leftovers:
            try:
                path.unlink(missing_ok=True)
            except OSError as e:
                logger.warning(f"[HelpTypst] 清理临时产物失败 {path}: {e}")

    def _schedule_artifact_cleanup(self, stem: str, delay: float = 30.0) -> None:
        """超时后子进程可能仍在写文件, 延迟再清一次它迟到的产物"""

        async def _cleanup() -> None:
            await asyncio.sleep(delay)
            self._discard_artifacts(stem)

        try:
            asyncio.get_running_loop().create_task(_cleanup())
        except RuntimeError:
            # 没有运行中的事件循环 (解释器退出等), 直接同步清一次
            self._discard_artifacts(stem)

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

        parts = sorted(self.data_dir.glob(f"{stem}_part*.webp"), key=_part_index)
        return [str(p) for p in parts] if parts else []

    async def _check_cache(
        self,
        json_path: Path,
        kv_key: str,
        img_path: Path,
        bg_image: Path | None = None,
    ) -> bool:
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

            # 4. 当前配置快照 (背景图由调用方显式传入, 与本次编译用的是同一张)
            current_config = self._get_config_snapshot(bg_image)

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
