import asyncio
import time
import uuid
from pathlib import Path
from typing import Optional, Callable, List, Dict, Any, Tuple
from concurrent.futures import ProcessPoolExecutor

from astrbot.api import logger

from ..domain import InternalCFG
from ..utils import calculate_hash, verify_image_header, RenderingConfig
from . import execute_render_task, RenderTask

class AsyncNullContext:
    async def __aenter__(self): return None
    async def __aexit__(self, exc_type, exc_value, traceback): return None

class RenderResult:
    """渲染结果封装"""
    def __init__(self, images: list[str], temp_files: list[Path]):
        self.images = images
        self.temp_files = temp_files

class TypstRenderer:
    def __init__(self, data_dir: Path, template_path: Path, font_dir: Path, config: RenderingConfig):
        self.data_dir = data_dir
        self.template_path = template_path
        self.font_dir = font_dir
        self.cfg = config
        self._compile_semaphore = asyncio.Semaphore(2)
        
        # 静态资源锁
        self._cache_locks = { k: asyncio.Lock() for k in InternalCFG.CACHE_FILES.keys() }

    async def render(self, data_provider: Callable[[Path], int], mode: str, query: Optional[str] = None) -> Tuple[Optional[RenderResult], str]:
        """
        核心渲染流程
        :param data_provider: 一个回调函数，接受 save_path, 返回 int (item_count)
        :param mode: command | event | filter
        :param query: 搜索关键词
        :return: (RenderResult, error_message)
        """
        
        # 1. 确定路径策略
        paths = self._resolve_paths(mode, query)
        json_path, img_path, hash_path = paths["json"], paths["img"], paths["hash"]
        is_temp, req_id = paths["is_temp"], paths["req_id"]

        # 待清理的中间文件 (JSON 和 原始 PNG)
        files_to_clean = []
        if is_temp: files_to_clean.extend([json_path, img_path])

        # 2. 获取锁 (仅静态模式需要)
        lock = self._cache_locks.get(mode) if not is_temp else None

        try:
            async with (lock or AsyncNullContext()):
                # --- Step A: 数据生成 ---
                try:
                    count = await asyncio.wait_for(
                        asyncio.to_thread(data_provider, json_path),
                        timeout=self.cfg.timeout_analysis
                    )
                except asyncio.TimeoutError:
                    return None, "数据分析超时，请检查插件列表是否过长"
                if count == 0: return None, "empty" # 特殊标记，由上层处理文案

                # --- Step B: 缓存校验 (仅静态) ---
                need_compile = True
                if not is_temp and json_path.exists():
                    need_compile = await self._check_cache(json_path, hash_path, img_path)

                if not need_compile:
                    # 直接用已有的 webp
                    cached_webps = self._find_cached_webps(img_path.stem)
                    if cached_webps:
                        return RenderResult(cached_webps, []), ""
                    else:
                        need_compile = True

                # --- Step C: Typst 编译 (进程池) ---
                if need_compile:
                    json_str = await asyncio.to_thread(json_path.read_text, encoding="utf-8")

                    # 构造 DTO
                    task = RenderTask(
                        template_path=str(self.template_path),
                        font_paths=[str(self.font_dir)],
                        json_str=json_str,
                        output_png_path=str(img_path),
                        output_dir=str(self.data_dir),
                        timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
                        query=query,
                        is_temp=is_temp,
                        req_id=req_id,
                        webp_limit=self.cfg.webp_limit,
                        split_height=self.cfg.split_height
                    )

                    # 调度执行
                    with ProcessPoolExecutor(max_workers=1) as temp_pool:
                        final_images = await asyncio.get_running_loop().run_in_executor(
                            temp_pool,
                            execute_render_task,
                            task
                        )

                    # 错误检查
                    if final_images and final_images[0].startswith("ERROR:"):
                        raise RuntimeError(final_images[0])
                    
                    if not final_images:
                        return None, "渲染未生成图片文件"

                    # 成功收尾
                    if not is_temp and hash_path:
                        new_hash = calculate_hash(json_str)
                        await asyncio.to_thread(hash_path.write_text, new_hash, encoding="utf-8")

                    if is_temp:
                        files_to_clean.extend([Path(p) for p in final_images])
                    
                    return RenderResult(final_images, files_to_clean), ""

        except Exception as e:
            logger.error(f"[HelpTypst] Render Error: {e}", exc_info=True)
            if not is_temp and hash_path and hash_path.exists(): hash_path.unlink()
            return None, f"渲染过程出错: {str(e)}"

        return None, "未知错误"

    def _resolve_paths(self, mode: str, query: Optional[str]) -> Dict[str, Any]:
        """计算文件路径"""
        if query:
            uid = str(uuid.uuid4())
            return {
                "json": self.data_dir / f"temp_{uid}.json",
                "img":  self.data_dir / f"temp_{uid}.png",
                "hash": None,
                "is_temp": True,
                "req_id": uid
            }
        else:
            base_name = InternalCFG.CACHE_FILES.get(mode, "cache_unknown")
            return {
                "json": self.data_dir / f"{base_name}.json",
                "img":  self.data_dir / f"{base_name}.png",
                "hash": self.data_dir / f"{base_name}.hash",
                "is_temp": False,
                "req_id": "static"
            }

    def _find_cached_webps(self, stem: str) -> List[str]:
        p1 = self.data_dir / f"{stem}.webp"
        if p1.exists(): return [str(p1)]
        
        parts = sorted(self.data_dir.glob(f"{stem}_part*.webp"), key=lambda x: x.name)
        return [str(p) for p in parts] if parts else []

    async def _check_cache(self, json_path: Path, hash_path: Path, img_path: Path) -> bool:
        """检查是否需要重新编译: True=需要, False=命中缓存"""
        try:
            json_content = await asyncio.to_thread(json_path.read_text, encoding="utf-8")
            current_hash = calculate_hash(json_content)
            
            last_hash = None
            if hash_path.exists():
                last_hash = await asyncio.to_thread(hash_path.read_text, encoding="utf-8")

            is_img_valid = False
            if img_path.exists():
                is_img_valid = await asyncio.to_thread(verify_image_header, img_path)
            
            if last_hash == current_hash and is_img_valid:
                logger.debug("[HelpTypst] 缓存命中。")
                return False # 不需要编译
            return True
        except Exception:
            return True