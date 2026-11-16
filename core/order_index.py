"""「编号 → 插件名」快照

面板编号是渲染那一刻的阅读顺序。插件增删、分类调整都会让同一编号指向别的插件,
而用户引用一张旧面板图再回一个数字时, 指的显然是**那张图**上的编号。这里把每次静态
面板渲染的编号映射落盘, 解析引用时按图取快照, 编号就不会被后来的重排带偏。
"""

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from astrbot.api import logger

from ..domain import InternalCFG, PluginMetadata


class OrderSnapshotStore:
    """每个静态面板最近一次的编号映射 (落盘, 写入串行)

    只保留最近一次: 面板产物文件名固定 (cache_menu_*), 同一面板的新图会覆盖旧图,
    旧快照对应的图已经不在数据目录里, 留着也匹配不上。
    """

    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / InternalCFG.NAME_ORDER_INDEX
        self._lock = threading.Lock()

    # ---- 写入 ----

    def record(self, mode: str, plugins: list[PluginMetadata]) -> None:
        """记录某个面板本次渲染的编号映射"""
        orders = {str(p.order): p.name for p in plugins if p.order > 0 and p.name}
        if not orders:
            return
        with self._lock:
            snapshots = self._read().get("snapshots")
            if not isinstance(snapshots, dict):
                snapshots = {}
            snapshots[mode] = {
                "generated_at": time.time(),
                "orders": orders,
            }
            self._write(
                {
                    "version": InternalCFG.ORDER_INDEX_VERSION,
                    "snapshots": snapshots,
                }
            )

    # ---- 读取 ----

    def lookup(self, mode: str, order: int) -> str | None:
        """按面板与编号取插件名; 没有快照或编号不在图里时返回 None"""
        snapshots = self._read().get("snapshots")
        if not isinstance(snapshots, dict):
            return None
        entry = snapshots.get(mode)
        if not isinstance(entry, dict):
            return None
        orders = entry.get("orders")
        if not isinstance(orders, dict):
            return None
        name = orders.get(str(order))
        return str(name) if name else None

    # ---- 内部 ----

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as e:
            # 快照只是旁路数据: 读坏了按「没有快照」处理, 下次渲染会整份重写
            logger.debug(f"[HelpTypst] 读取编号快照失败: {e}")
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, payload: dict[str, Any]) -> None:
        tmp = self._path.with_name(f"{self._path.name}.tmp")
        try:
            tmp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(tmp, self._path)
        except OSError as e:
            tmp.unlink(missing_ok=True)
            logger.warning(f"[HelpTypst] 写入编号快照失败: {e}")
