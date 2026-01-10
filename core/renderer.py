import asyncio
import time
import uuid
import json
from pathlib import Path
from typing import Optional, Callable, List, Dict, Any, Tuple
from concurrent.futures import ProcessPoolExecutor

from astrbot.api import logger

from ..domain import InternalCFG
from ..utils import calculate_hash, verify_image_header, RenderingConfig
from . import execute_render_task, RenderTask

class AsyncNullContext: # 异步空上下文
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
        self._compile_semaphore = asyncio.Semaphore(self.cfg.max_concurrent_tasks)
        self._cache_locks = { k: asyncio.Lock() for k in InternalCFG.CACHE_FILES.keys() }

        # 静态资源锁
        self._cache_locks = { k: asyncio.Lock() for k in InternalCFG.CACHE_FILES.keys() }

    def _get_config_snapshot(self) -> Dict[str, Any]:
        """渲染配置的快照字典"""
        snapshot = {}
        for key in InternalCFG.CACHE_SENSITIVE_CONFIGS:
            if hasattr(self.cfg, key):
                snapshot[key] = getattr(self.cfg, key)
        return snapshot

    async def render(self, data_provider: Callable[[Path], int], mode: str, query: Optional[str] = None) -> Tuple[Optional[RenderResult], str]:
        """核心渲染流程"""
        # 1. 确定路径策略
        paths = self._resolve_paths(mode, query)
        json_path, img_path, hash_path = paths["json"], paths["img"], paths["hash"]
        is_temp, req_id = paths["is_temp"], paths["req_id"]

        # 2. 获取锁 (仅静态模式需要)
        lock = self._cache_locks.get(mode) if not is_temp else None

        try:
            async with (lock or AsyncNullContext()):
                # --- 1. 数据生成 ---
                try:
                    count = await asyncio.wait_for(
                        asyncio.to_thread(data_provider, json_path),
                        timeout=self.cfg.timeout_analysis
                    )
                except asyncio.TimeoutError:
                    if is_temp and json_path.exists(): json_path.unlink(missing_ok=True)
                    return None, "数据分析超时，请检查插件列表是否过长"

                if count == 0:
                    if is_temp and json_path.exists(): json_path.unlink(missing_ok=True) 
                    return None, "empty"

                # --- 2. 缓存校验 (仅静态) ---
                need_compile = True
                if not is_temp and json_path.exists():
                    # hash + config 双校验
                    need_compile = await self._check_cache(json_path, hash_path, img_path)

                if not need_compile:
                    cached_webps = self._find_cached_webps(img_path.stem)
                    if cached_webps:
                        return RenderResult(cached_webps, []), ""
                    else:
                        need_compile = True

                # --- 3. Typst 编译 ---
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
                        split_height=self.cfg.split_height,
                        ppi=self.cfg.ppi
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

                    # --- 4. 缓存写入 ---
                    if not is_temp and hash_path:
                        new_content_hash = calculate_hash(json_str)
                        current_config_snapshot = self._get_config_snapshot()

                        meta_data = {
                            "content_hash": new_content_hash,
                            "config": current_config_snapshot
                        }

                        await asyncio.to_thread(
                            hash_path.write_text, 
                            json.dumps(meta_data, ensure_ascii=False), 
                            encoding="utf-8"
                        )

                    # --- 5. 清理 ---
                    files_to_clean = []
                    if is_temp:
                        files_to_clean.extend([json_path, img_path])
                        files_to_clean.extend([Path(p) for p in final_images])

                    return RenderResult(final_images, files_to_clean), ""

        except Exception as e:
            logger.error(f"[HelpTypst] Render Error: {e}", exc_info=True)

            if is_temp:
                try:
                    if json_path.exists(): json_path.unlink()
                    if img_path.exists(): img_path.unlink()
                except Exception:
                    pass

            if not is_temp and hash_path and hash_path.exists(): 
                hash_path.unlink()

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
        """检查是否需要重新编译"""
        try:
            # 1. 计算当前 Hash
            json_content = await asyncio.to_thread(json_path.read_text, encoding="utf-8")
            current_content_hash = calculate_hash(json_content)

            # 2. 读缓存
            if not hash_path.exists(): return True
            cached_data_str = await asyncio.to_thread(hash_path.read_text, encoding="utf-8")

            # 3. 解析缓存
            try:
                cached_meta = json.loads(cached_data_str)
                cached_content_hash = cached_meta.get("content_hash")
                cached_config = cached_meta.get("config", {})
            except json.JSONDecodeError:
                # 兼容性处理
                cached_content_hash = cached_data_str.strip()
                cached_config = {} 

            # 4. 当前配置快照
            current_config = self._get_config_snapshot()

            # 5. 图片完整性校验
            is_img_valid = False
            if img_path.exists():
                is_img_valid = await asyncio.to_thread(verify_image_header, img_path)

            # 6. 比对：内容一致 AND 配置一致 AND 图片有效
            if (cached_content_hash == current_content_hash and 
                cached_config == current_config and 
                is_img_valid):

                logger.debug("[HelpTypst] 缓存命中 (Content + Config)。")
                return False # 不需要编译

            logger.debug(f"[HelpTypst] 缓存失效。ConfigMatch={cached_config == current_config}")
            return True

        except Exception as e:
            logger.warning(f"[HelpTypst] 缓存校验异常，强制重绘: {e}")
            return True