import math
import uuid
import hashlib
import asyncio
import re
import typst
from PIL import Image
from pathlib import Path
from typing import List, Dict

from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, StarTools
import astrbot.api.message_components as Comp

from .core import CommandAnalyzer, EventAnalyzer, FilterAnalyzer

class AsyncNullContext: # 异步空上下文
    async def __aenter__(self):
        return None
    async def __aexit__(self, exc_type, exc_value, traceback):
        return None

class HelpTypst(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.cmd_analyzer = CommandAnalyzer(context)
        self.evt_analyzer = EventAnalyzer(context)
        self.flt_analyzer = FilterAnalyzer(context)

        # 资源
        self.plugin_dir = Path(__file__).parent
        self.template_path = self.plugin_dir / "templates" / "base.typ"
        self.font_dir = self.plugin_dir / "resources" / "fonts"

        # 数据
        self.data_dir = StarTools.get_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # 缓存
        self.CACHE_FILES = {
            "command": "cache_menu_command",
            "event":   "cache_menu_event",
            "filter":  "cache_menu_filter"
        }

        # 🔒 异步锁应对静态并发冲突
        self._cache_locks = {
            "command": asyncio.Lock(),
            "event":   asyncio.Lock(),
            "filter":  asyncio.Lock()
        }

    def _parse_query(self, event: AstrMessageEvent) -> str | None:
        raw_text = event.message_str.strip()
        parts = raw_text.split(maxsplit=1)
        return parts[1].strip() if len(parts) > 1 else None

    def _get_file_paths(self, mode: str, query: str | None = None) -> Dict[str, Path | bool | None]:
        """
        根据模式和查询参数，决定文件路径策略
        返回字典包含 Path 对象或布尔值
        }
        """
        if query:
            # === 动态 (搜索) ===
            # 使用 UUID 避免并发冲突
            uid = str(uuid.uuid4())
            return {
                "json": self.data_dir / f"temp_{uid}.json",
                "img":  self.data_dir / f"temp_{uid}.png",
                "hash": None,
                "is_temp": True
            }
        else:
            # === 静态 (缓存) ===
            # 使用固定文件名，分离不同指令的缓存
            base_name = self.CACHE_FILES.get(mode, "cache_unknown")
            return {
                "json": self.data_dir / f"{base_name}.json",
                "img":  self.data_dir / f"{base_name}.png",
                "hash": self.data_dir / f"{base_name}.hash", # 用于存储上次数据的 Hash
                "is_temp": False
            }

    def _calculate_hash(self, content: str) -> str:
        """计算字符串的 MD5 哈希"""
        return hashlib.md5(content.encode("utf-8")).hexdigest()

    async def _render(self, event: AstrMessageEvent, analyzer, title: str, mode: str, query: str | None = None):
        """
        渲染流程：
        1. 静态请求 -> 检查数据变更 -> 有变更则重绘，无变更则复用 -> 发送
        2. 动态请求 -> 生成 UUID 文件 -> 渲染 -> 发送 -> 删除
        """
        if query:
            yield event.plain_result(f"正在搜索 '{query}'...")
        else:
            yield event.plain_result("正在渲染菜单..." if mode == "command" else "正在获取列表...")

        paths = self._get_file_paths(mode, query)
        json_path = paths["json"]
        img_path = paths["img"]
        is_temp = paths["is_temp"]

        # 待清理列表
        files_to_clean: List[Path] = []
        if is_temp and isinstance(json_path, Path) and isinstance(img_path, Path):
            files_to_clean = [json_path, img_path]

        # 🔒 获取静态锁
        lock = self._cache_locks.get(mode) if not is_temp else None
        lock_ctx = lock if lock else AsyncNullContext()

        try:
            # 🔒 同一时间只执行一个静态生成的任务
            async with lock_ctx:
                # 1. 生成数据
                try:
                    count = await asyncio.wait_for(
                        asyncio.to_thread(analyzer.generate_render_data, json_path, title=title, mode=mode, query=query),
                        timeout=10.0 # 视插件数量调整，一般已足够，日后会把此类提取到专门的 constants.py
                    )
                except asyncio.TimeoutError:
                    yield event.plain_result("数据分析超时，请检查插件列表是否过长。")
                    return

                if count == 0:
                    target = "事件监听器" if mode == "event" else "插件或指令"
                    msg = f"未找到包含 '{query}' 的{target}。" if query else f"当前没有可显示的{target}。"
                    yield event.plain_result(msg)
                    return

                # 2. 缓存检查
                if not isinstance(json_path, Path):
                    raise ValueError("JSON path invalid")

                json_content = await asyncio.to_thread(json_path.read_text, encoding="utf-8")
                need_compile = True

                if not is_temp:
                    current_hash = self._calculate_hash(json_content)
                    last_hash = None
                    hash_path = paths["hash"]

                    if isinstance(hash_path, Path) and hash_path.exists():
                        last_hash = await asyncio.to_thread(hash_path.read_text, encoding="utf-8")

                    # 验证 & 自愈逻辑
                    is_image_valid = False
                    if isinstance(img_path, Path) and img_path.exists():
                        try:
                            await asyncio.to_thread(self._verify_image_header, img_path)
                            is_image_valid = True
                        except Exception:
                            logger.warning(f"[HelpTypst] 检测到缓存图片损坏 {img_path}，将强制重绘。")
                            is_image_valid = False

                    if last_hash == current_hash and is_image_valid:
                        logger.info(f"[HelpTypst] {mode} 缓存命中且校验通过。")
                        need_compile = False
                    else:
                        if isinstance(hash_path, Path):
                            await asyncio.to_thread(hash_path.write_text, current_hash, encoding="utf-8")

                # 3. Typst 编译
                if need_compile:
                    sys_inputs = {"json_string": json_content}
                    if query:
                        sys_inputs["query_regex"] = re.escape(query)

                    try:
                        await asyncio.wait_for(
                            asyncio.to_thread(
                                typst.compile,
                                str(self.template_path),     
                                output=str(img_path),
                                font_paths=[str(self.font_dir)],
                                format="png", ppi=144.0, 
                                sys_inputs=sys_inputs
                            ),
                            timeout=30.0 # 视插件数量调整，一般已足够，日后会把此类提取到专门的 constants.py
                        )
                    except asyncio.TimeoutError:
                        yield event.plain_result("渲染超时 (Typst Compile Timeout)。")
                        return
                    except Exception as e:
                        # 编译失败删除 Hash 文件，防止下次误判为缓存命中
                        hash_path = paths["hash"]
                        if not is_temp and isinstance(hash_path, Path) and hash_path.exists():
                            hash_path.unlink()
                        raise e

            # --- 🔓 锁释放 ---
            if isinstance(img_path, Path) and img_path.exists():
                images_to_send = await asyncio.to_thread(
                    self._process_image, img_path, bool(is_temp), str(uuid.uuid4())
                )

                if is_temp:
                    files_to_clean.extend([Path(p) for p in images_to_send])

                if images_to_send:
                    comps = [Comp.Image.fromFileSystem(p) for p in images_to_send]
                    yield event.chain_result(comps)
                else:
                    yield event.plain_result("图片处理异常。")
            else:
                yield event.plain_result("渲染未生成图片文件。")

        except Exception as e:
            logger.error(f"渲染流程异常: {e}", exc_info=True)
            yield event.plain_result(f"处理出错: {e}")

        finally:
            if files_to_clean:
                await asyncio.to_thread(self._cleanup_files, files_to_clean)

    def _verify_image_header(self, path: Path):
        """简单的图片完整性校验"""
        with Image.open(path) as img:
            img.verify()

    def _process_image(self, img_path: Path, is_temp: bool, req_id: str) -> List[str]:
        """
        图片处理逻辑：转 WebP，超长切分
        返回生成的图片路径列表
        """
        images = []
        try:
            with Image.open(img_path) as img:
                WEBP_LIMIT = 16383
                SPLIT_HEIGHT = 16000

                # 输出文件的前缀策略
                # temp → req_id 区分
                # static → img_path.stem（覆盖旧切片）
                if is_temp:
                    stem = f"temp_{req_id}"
                else:
                    stem = img_path.stem 

                if img.height <= WEBP_LIMIT:
                    # 直接转 WebP
                    webp_path = self.data_dir / f"{stem}.webp"
                    img.save(webp_path, "WEBP", quality=80, method=6)
                    images.append(str(webp_path))
                else:
                    # 长图切分
                    width, total_height = img.size
                    chunks = math.ceil(total_height / SPLIT_HEIGHT)
                    for i in range(chunks):
                        top = i * SPLIT_HEIGHT
                        bottom = min((i + 1) * SPLIT_HEIGHT, total_height)

                        box = (0, top, width, bottom)
                        chunk = img.crop(box)

                        chunk_path = self.data_dir / f"{stem}_part{i+1}.webp"
                        chunk.save(chunk_path, "WEBP", quality=80, method=6)
                        images.append(str(chunk_path))
        except Exception as e:
            logger.error(f"图片处理失败: {e}")

        return images

    def _cleanup_files(self, file_list: List[Path]):
        """清理临时文件"""
        for path in file_list:
            try:
                if path.exists():
                    path.unlink()
            except Exception as e:
                logger.warning(f"清理临时文件失败 {path}: {e}")

    @filter.command("helps")
    async def show_menu(self, event: AstrMessageEvent):
        """显示指令菜单"""
        query = self._parse_query(event)
        async for result in self._render(event, self.cmd_analyzer, "AstrBot 指令菜单", mode="command", query=query):
            yield result

    @filter.command("events")
    async def show_events(self, event: AstrMessageEvent):
        """显示事件监听列表"""
        query = self._parse_query(event)
        async for result in self._render(event, self.evt_analyzer, "AstrBot 事件监听", mode="event", query=query):
            yield result

    @filter.command("filters")
    async def show_filters(self, event: AstrMessageEvent):
        """显示过滤器详情"""
        query = self._parse_query(event)
        async for result in self._render(event, self.flt_analyzer, "AstrBot 过滤器分析", mode="filter", query=query):
            yield result

    async def terminate(self):
        """插件卸载时清理"""
        logger.info("[HelpTypst] 插件正在卸载，正在清理临时资源...")
        try:
            for f in self.data_dir.glob("temp_*"):
                try:
                    f.unlink()
                except:
                    pass
        except Exception as e:
            logger.warning(f"清理失败: {e}")