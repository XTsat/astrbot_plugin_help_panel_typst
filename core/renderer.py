import asyncio
import json
import os
import random
import re
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.api.star import Star

from ..domain import InternalCFG, RenderFailure, TypstPluginConfig
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
    ext_pattern = "|".join(
        re.escape(ext.lstrip(".")) for ext in InternalCFG.FORMAT_EXT.values()
    )
    match = re.search(rf"_part(\d+)\.(?:{ext_pattern})$", path.name)
    return int(match.group(1)) if match else 0


class AsyncNullContext:  # 异步空上下文
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc_value, traceback):
        return None


@dataclass(frozen=True, slots=True)
class RenderPaths:
    """一次渲染的落盘路径策略

    json 是数据落点, image 是本次编译的直接产物, kv_key 是静态缓存的元数据键
    (临时路径没有缓存, 为 None)。三者绑在一起返回, 调用方不必按字符串键取值。
    """

    json: Path
    image: Path
    kv_key: str | None
    is_temp: bool
    req_id: str


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
        # 超时编译的看门狗句柄 (stem → TimerHandle): 子进程真挂死时由它强制收尾,
        # 否则令牌永不归还, 并发上限被占满后只能重载插件恢复
        self._token_holds: dict[str, asyncio.TimerHandle] = {}

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

    def get_config_snapshot(self, bg_image: Path | None = None) -> dict[str, Any]:
        """渲染配置快照 (预览页把它并入缓存键, 配置/模板/背景变化时自动失效)"""
        return self._get_config_snapshot(bg_image)

    def _resolve_background_image(self, deterministic: bool = False) -> Path | None:
        """解析头部背景图

        优先级:
          1. header_background: 显式指定单个图片文件 (不使用随机)
          2. background_dir:    自定义背景目录, 只扫描该目录内的图片
          3. 默认背景目录:      数据目录下 backgrounds/ 子目录
        目录扫描规则: 该目录根下的图片文件 (排除 cache_/temp_ 前缀), 多张时按
        background_random 决定随机选一张或取文件名排序第一张。

        deterministic: 预览页用。为 True 时即使开启随机也固定取排序后的第一张,
        否则同一套样式每次请求可能换背景, 预览与缓存都无法稳定。
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

            if len(candidates) > 1 and self.cfg.background_random and not deterministic:
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

    def resolve_background_image(self, deterministic: bool = False) -> Path | None:
        """当前配置下实际使用的背景图 (预览页用来标记「当前生效」项)"""
        return self._resolve_background_image(deterministic)

    def list_background_choices(self) -> list[tuple[str, Path]]:
        """列出预览页可选的背景图 (文件名 → 路径, 按文件名排序)

        合并显式配置的单图、自定义背景目录与默认背景目录; 预览请求只按文件名
        回传选择, 因此同名图片由先出现的来源占位, 保证解析结果可复现。
        """
        choices: dict[str, Path] = {}
        explicit = (self.cfg.header_background or "").strip()
        if explicit:
            path = Path(explicit)
            if (
                path.is_file()
                and path.suffix.lower() in InternalCFG.BACKGROUND_IMAGE_EXTS
                and verify_image_header(path)
                and verify_image_format_matches_extension(path)
            ):
                choices[path.name] = path

        scan_dirs: list[Path] = []
        custom_dir = (self.cfg.background_dir or "").strip()
        if custom_dir:
            scan_dirs.append(Path(custom_dir))
        scan_dirs.append(self.data_dir / InternalCFG.NAME_BACKGROUND_DIR)
        for scan_dir in scan_dirs:
            for path in self._scan_background_dir(scan_dir):
                choices.setdefault(path.name, path)

        return sorted(choices.items(), key=lambda item: item[0].lower())

    async def render(
        self,
        data_provider: Callable[[Path], int],
        mode: str,
        query: str | None = None,
        force_temp: bool = False,
    ) -> tuple[RenderResult | None, str]:
        """核心渲染流程

        force_temp: 网页预览用。为 True 时即使没有搜索词也走 temp_* 临时路径,
        不读写静态缓存 —— 预览的样式是随手调的, 不能污染正式发图缓存。
        """
        # 1. 确定路径策略
        paths = self._resolve_paths(mode, query, force_temp)
        json_path, img_path, kv_key = paths.json, paths.image, paths.kv_key
        is_temp, req_id = paths.is_temp, paths.req_id

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
                    return None, "数据生成超时，请检查插件列表是否过长"

                if count == 0:
                    if is_temp and json_path.exists():
                        json_path.unlink(missing_ok=True)
                    return None, RenderFailure.EMPTY

                # --- 2. 缓存校验 (仅静态) ---
                need_compile = True
                if not is_temp and json_path.exists():
                    # hash + config 双校验
                    need_compile = await self._check_cache(
                        json_path, kv_key, img_path, bg_image
                    )

                if not need_compile:
                    cached_outputs = self._find_cached_outputs(img_path.stem)
                    if cached_outputs:
                        return RenderResult(cached_outputs, []), ""
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
                        output_format=self.cfg.rendering.output_format,
                        ppi=self.cfg.rendering.ppi,
                        bg_image_path=bg_image_path,
                        root_dir=root_dir,
                        hero_header=self.cfg.hero_header,
                    )

                    # 调度执行: 全局并发上限 + 编译超时, 避免一次挂死永久持有 mode 锁
                    try:
                        final_images = await self._compile_once(task, artifact_stem)
                    except asyncio.TimeoutError:
                        logger.warning(
                            f"[HelpTypst] 编译或排队超时, 已放弃本次渲染: mode={mode}"
                        )
                        if is_temp:
                            json_path.unlink(missing_ok=True)
                        return None, "渲染超时，请稍后重试或减少插件数量"

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

            # 详细异常（含部署路径）只进日志，聊天窗口给通用提示
            return None, "渲染失败：请稍后重试；若持续失败请查看插件日志"

        return None, "未知错误"

    def _commit_cache_images(
        self,
        cache_png: Path,
        compile_png: Path,
        produced_outputs: list[str],
        compile_stem: str,
    ) -> list[str]:
        """把临时 stem 上的编译产物原子替换为正式缓存文件

        os.replace 是原子操作: 正式缓存名在任何时刻都指向一份完整文件, 不会出现
        「文件被删掉」的窗口, 并发请求正在发送上一张图时也不会读不到文件。
        """
        committed: list[Path] = []
        os.replace(compile_png, cache_png)
        for produced in produced_outputs:
            if Path(produced) == compile_png:
                # PNG 输出且 stem 与编译产物同名: 产物已随上面的 replace 落位
                committed.append(cache_png)
                continue
            suffix = Path(produced).name[len(compile_stem) :]
            target = self.data_dir / f"{cache_png.stem}{suffix}"
            os.replace(produced, target)
            committed.append(target)

        # 单图 ↔ 分片、分片数变少、或换了发送格式时, 清掉本次没有产出的旧产物
        self._discard_stale_outputs(cache_png.stem, committed)
        self._discard_artifacts(compile_stem)
        return [str(p) for p in committed]

    def _discard_stale_outputs(self, stem: str, keep: list[Path]) -> None:
        """删除某个静态 mode 下本次未产出的旧图 (含旧分片, 不限扩展名)

        只匹配本 mode 自己的文件名: cache_menu_command 与 cache_menu_command_detail
        互为前缀, 用 glob(f"{stem}*") 会误删另一个模式的缓存。
        换发送格式后旧格式文件也在这里清掉。
        """
        keep_names = {p.name for p in keep}
        exts = "|".join(
            re.escape(ext.lstrip(".")) for ext in InternalCFG.FORMAT_EXT.values()
        )
        # <stem>.png 是缓存的编译产物 (PNG 输出格式下也是输出本身), 任何情况下都不能删
        single_names = {
            f"{stem}{ext}"
            for ext in InternalCFG.FORMAT_EXT.values()
            if ext != InternalCFG.FORMAT_EXT["png"]
        }
        part_pattern = re.compile(rf"^{re.escape(stem)}_part\d+\.(?:{exts})$")
        try:
            entries = list(self.data_dir.iterdir())
        except OSError as e:
            logger.warning(f"[HelpTypst] 清理旧缓存失败 {stem}: {e}")
            return
        for entry in entries:
            if entry.name in keep_names:
                continue
            if entry.name not in single_names and not part_pattern.match(entry.name):
                continue
            try:
                entry.unlink(missing_ok=True)
            except OSError as e:
                logger.warning(f"[HelpTypst] 清理旧缓存文件失败 {entry}: {e}")

    def _discard_artifacts(self, stem: str) -> None:
        """尽力删除某个 stem 的编译产物 (各格式单图 + 各格式分片 + Typst 单页 PNG)"""
        leftovers: list[Path] = []
        for ext in InternalCFG.FORMAT_EXT.values():
            leftovers.append(self.data_dir / f"{stem}{ext}")
            leftovers.extend(self.data_dir.glob(f"{stem}_part*{ext}"))
        # 分页编译的中间产物: <stem>.pageN.png
        leftovers.extend(self.data_dir.glob(f"{stem}.page*.png"))
        for path in leftovers:
            try:
                path.unlink(missing_ok=True)
            except OSError as e:
                logger.warning(f"[HelpTypst] 清理临时产物失败 {path}: {e}")

    async def _compile_once(self, task: RenderTask, artifact_stem: str) -> list[str]:
        """占一个并发令牌执行一次编译, 并在异常路径决定令牌何时归还

        超时/取消时子进程仍在跑, 若立刻归还令牌, 并发编译数就会突破
        max_concurrent_tasks, 迟到的产物也可能与下一个请求的清理互相踩;
        因此令牌要等 worker 真正结束后再交还, 产物的清理也挪到那之后。
        """
        loop = asyncio.get_running_loop()
        try:
            await asyncio.wait_for(
                self._compile_semaphore.acquire(),
                # 上一次超时的子进程可能还在跑: 排队等太久就不该继续把请求挂死
                timeout=float(self.cfg.rendering.timeout_compile),
            )
        except asyncio.TimeoutError:
            logger.warning("[HelpTypst] 等待编译并发令牌超时, 已放弃本次渲染")
            raise
        try:
            pool = ProcessPoolExecutor(max_workers=1)
        except BaseException:
            self._compile_semaphore.release()
            raise

        future: Future[list[str]] | None = None
        try:
            future = pool.submit(execute_render_task, task)
            images = await asyncio.wait_for(
                asyncio.wrap_future(future),
                # 下限已由 config.load / 预览样式统一夹紧, 这里不再另设兜底
                timeout=float(self.cfg.rendering.timeout_compile),
            )
        except BaseException:
            if future is None or future.done():
                # 子进程已退出: 清掉本次不再使用的产物, 令牌可立即归还
                self._discard_artifacts(artifact_stem)
                pool.shutdown(wait=False, cancel_futures=True)
                self._compile_semaphore.release()
            else:
                self._hold_token_until_worker_done(pool, future, artifact_stem, loop)
            raise

        # 不能写成 try/else: 成功路径在 try 里 return 会跳过 else, 令牌就再也还不回去
        pool.shutdown(wait=False, cancel_futures=True)
        self._compile_semaphore.release()
        return images

    def _hold_token_until_worker_done(
        self,
        pool: ProcessPoolExecutor,
        future: Future[list[str]],
        artifact_stem: str,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        """超时/取消的编译: 等子进程真正退出后再清迟到产物并归还令牌

        子进程卡死不退出时 done 回调永不触发, 因此同时挂一个看门狗: 持有超过
        `COMPILE_TOKEN_HOLD_FACTOR` 倍 `timeout_compile` 就强制收尾, 把「并发令牌
        被永久占满」降级成「这一次编译彻底放弃」。
        """
        hold_limit = (
            float(self.cfg.rendering.timeout_compile)
            * InternalCFG.COMPILE_TOKEN_HOLD_FACTOR
        )
        self._token_holds[artifact_stem] = loop.call_later(
            hold_limit, self._abandon_hung_worker, pool, artifact_stem
        )

        def _on_worker_done(_future: Future[list[str]]) -> None:
            try:
                loop.call_soon_threadsafe(
                    self._finish_timed_out_compile, pool, artifact_stem
                )
            except RuntimeError:
                # 事件循环已关闭 (插件卸载): 清产物并关池; 信号量已无意义, 不再碰
                self._token_holds.pop(artifact_stem, None)
                self._discard_artifacts(artifact_stem)
                pool.shutdown(wait=False, cancel_futures=True)

        future.add_done_callback(_on_worker_done)

    def _finish_timed_out_compile(
        self, pool: ProcessPoolExecutor, artifact_stem: str
    ) -> None:
        """超时编译的收尾: 清迟到产物 → 归还令牌 → 关闭进程池"""
        if not self._release_token_hold(artifact_stem):
            return  # 看门狗已经收尾过, 令牌与进程池都不必再动
        self._discard_artifacts(artifact_stem)
        self._compile_semaphore.release()
        pool.shutdown(wait=False, cancel_futures=True)
        logger.info("[HelpTypst] 超时的编译子进程已结束, 已清理迟到产物并归还并发令牌")

    def _abandon_hung_worker(
        self, pool: ProcessPoolExecutor, artifact_stem: str
    ) -> None:
        """看门狗: 子进程迟迟不退出时放弃本次编译并交还令牌, 保证后续渲染还能跑"""
        if not self._release_token_hold(artifact_stem):
            return
        self._discard_artifacts(artifact_stem)
        self._compile_semaphore.release()
        pool.shutdown(wait=False, cancel_futures=True)
        logger.error(
            "[HelpTypst] 编译子进程超过超时上限仍未退出, 已放弃本次编译并归还并发令牌"
        )

    def _release_token_hold(self, artifact_stem: str) -> bool:
        """取回并取消该 stem 的看门狗; 已被收尾过 (无记录) 时返回 False"""
        handle = self._token_holds.pop(artifact_stem, None)
        if handle is None:
            return False
        handle.cancel()
        return True

    def _resolve_paths(
        self, mode: str, query: str | None, force_temp: bool = False
    ) -> RenderPaths:
        """计算文件路径"""
        if query or force_temp:
            uid = str(uuid.uuid4())
            return RenderPaths(
                json=self.data_dir / f"temp_{uid}.json",
                image=self.data_dir / f"temp_{uid}.png",
                kv_key=None,
                is_temp=True,
                req_id=uid,
            )
        # 未知 mode 落在共用兜底名上: 没有独立缓存文件与锁 (见 AGENTS §5.4)
        stem = InternalCFG.CACHE_FILES.get(mode, "cache_unknown")
        return RenderPaths(
            json=self.data_dir / f"{stem}.json",
            image=self.data_dir / f"{stem}.png",
            kv_key=f"typst_cache_{mode}",
            is_temp=False,
            req_id="static",
        )

    def _find_cached_outputs(self, stem: str) -> list[str]:
        """按当前发送格式查找产物: 先找分片, 再找单图

        分片优先: PNG 格式下缓存里的编译产物本身就是 `<stem>.png`,
        先看单图会把「第一页原图」当成整张面板, 漏掉真正要发的分片。
        """
        ext = InternalCFG.FORMAT_EXT.get(
            self.cfg.rendering.output_format, InternalCFG.FORMAT_EXT["webp"]
        )
        parts = sorted(self.data_dir.glob(f"{stem}_part*{ext}"), key=_part_index)
        if parts:
            return [str(p) for p in parts]

        single = self.data_dir / f"{stem}{ext}"
        return [str(single)] if single.exists() else []

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
