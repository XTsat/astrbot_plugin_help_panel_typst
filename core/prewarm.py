import asyncio
import time
from collections.abc import Awaitable, Callable, Coroutine
from pathlib import Path
from typing import Any

from astrbot.api import logger

from ..domain import InternalCFG, TypstPluginConfig
from .renderer import TypstRenderer

# 数据流构造器: 传入 mode, 返回可直接交给渲染器的数据生成函数 (取不到返回 None)
ProviderGetter = Callable[[str], Awaitable[Callable[[Path], int] | None]]


class PrewarmService:
    """静态面板缓存预热

    四个静态面板 (指令 / 详细指令 / 事件 / 过滤器) 的图平时只在有人请求时才编译,
    首次请求要等整轮分析与 Typst 编译。本服务把这些图提前编进缓存, 把等待挪到空闲期:
    启动完成预热一轮, 之后定时核对插件条目指纹, 变了 (装 / 卸 / 启 / 停 / 升级) 再编一轮。

    多跑一轮的代价很小 —— 缓存仍由渲染器的内容 hash + 配置快照校验, 内容没变时
    render() 直接返回命中结果, 不会重复编译。
    """

    def __init__(
        self,
        *,
        renderer: TypstRenderer,
        provider_getter: ProviderGetter,
        fingerprint_getter: Callable[[], str],
        config: TypstPluginConfig,
        modes: tuple[str, ...] = InternalCFG.PREWARM_MODES,
    ) -> None:
        self._renderer = renderer
        self._provider_getter = provider_getter
        self._fingerprint_getter = fingerprint_getter
        self._cfg = config
        self._modes = modes
        # 上一轮预热成功时的插件指纹; 空串表示「还没成功跑过」, 下次检查必定预热
        self._last_fingerprint = ""
        self._last_run_at = 0.0
        self._loop_task: asyncio.Task[None] | None = None
        self._pending: set[asyncio.Task[None]] = set()
        # 串行化「跑一轮预热」: 定时轮询、请求后检查与手动触发可能同时到达,
        # 并发跑只会让同一张图被编两遍
        self._run_lock = asyncio.Lock()

    # ---- 生命周期 ----

    def start(self) -> None:
        """启动后台轮询 (插件 initialize 时调用; 重复调用无副作用)"""
        if self._loop_task is not None and not self._loop_task.done():
            return
        if not self._cfg.rendering.prewarm_enabled:
            logger.info("[HelpTypst] 自动预热已关闭 (prewarm_enabled=false)")
            return
        self._loop_task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        """停止后台轮询与在途预热 (插件 terminate 时调用)"""
        tasks = [
            task
            for task in (self._loop_task, *self._pending)
            if task is not None and not task.done()
        ]
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                # 卸载阶段的清理异常只记账, 不阻断 terminate 的其余步骤
                logger.warning(f"[HelpTypst] 停止预热任务时出错: {e}")
        self._loop_task = None
        self._pending.clear()

    # ---- 触发 ----

    def notify_change(self, reason: str) -> None:
        """请求一次「指纹变了就预热」的检查 (非阻塞)

        插件条目在别的机器上被改动时, 下一次面板请求就是最早的信号, 不必干等轮询。
        """
        self._spawn(lambda: self._check_and_warm(reason))

    async def warm_now(self) -> list[str]:
        """立即预热一轮 (管理员指令用, 不受 prewarm_enabled 约束)

        返回本轮真正产出图片的 mode 列表, 空列表表示没编出任何一张。
        """
        async with self._run_lock:
            warmed, complete = await self._warm_all("手动触发", force=True)
            if complete:
                self._remember_fingerprint(warmed)
            return warmed

    def status(self) -> dict[str, object]:
        """预热状态快照 (调试 / 日志用)"""
        return {
            "enabled": self._cfg.rendering.prewarm_enabled,
            "modes": list(self._modes),
            "last_fingerprint": self._last_fingerprint,
            "last_run_at": self._last_run_at,
            "running": bool(self._loop_task and not self._loop_task.done()),
        }

    # ---- 内部 ----

    def _spawn(self, factory: Callable[[], Coroutine[Any, Any, list[str]]]) -> None:
        """把一次预热检查丢到后台, 失败只记日志不影响调用方

        传工厂而非协程对象: 关闭预热时协程已经建好却没人 await, 会留下
        「coroutine was never awaited」告警。
        """
        if not self._cfg.rendering.prewarm_enabled:
            return
        try:
            task = asyncio.create_task(factory())
        except RuntimeError as e:
            # 没有运行中的事件循环 (卸载阶段) 时直接放弃本轮
            logger.debug(f"[HelpTypst] 跳过预热检查: {e}")
            return
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _loop(self) -> None:
        # 启动延迟: 先让插件加载与首批用户请求拿到 CPU
        await asyncio.sleep(InternalCFG.PREWARM_STARTUP_DELAY)
        while True:
            try:
                await self._check_and_warm("定时检查")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                # 预热失败只降级为「下次请求照常现编」, 后台轮询本身不能因此死掉
                logger.warning(f"[HelpTypst] 预热轮询异常: {e}")
            interval = max(1, int(self._cfg.rendering.prewarm_interval)) * 60
            await asyncio.sleep(interval)

    async def _check_and_warm(self, reason: str) -> list[str]:
        """指纹没变就跳过 (内容层面的失效由渲染器的缓存校验兜底)"""
        async with self._run_lock:
            fingerprint = self._fingerprint_getter()
            if fingerprint and fingerprint == self._last_fingerprint:
                return []
            warmed, complete = await self._warm_all(reason)
            # 有模式没编出来时不留账: 下一轮还会补编 (超时/占满多半是暂时的)
            if complete:
                self._remember_fingerprint(warmed, fingerprint)
            return warmed

    def _remember_fingerprint(
        self, warmed: list[str], fingerprint: str | None = None
    ) -> None:
        """只在真的编出图之后记账, 中途失败时下一轮还会重试

        指纹读取失败 (空串) 时不留账: 否则空指纹会被当成「与上次相同」, 之后永不预热。
        """
        if not warmed:
            return
        if fingerprint is None:
            fingerprint = self._fingerprint_getter()
        if fingerprint:
            self._last_fingerprint = fingerprint
            self._last_run_at = time.time()

    async def _warm_all(
        self, reason: str, force: bool = False
    ) -> tuple[list[str], bool]:
        """按 PREWARM_MODES 顺序逐个预热

        返回 (真正出图的 mode 列表, 是否全部成功)。全部成功才值得记账, 否则下一轮
        定时检查会补编落下的那几张。
        """
        warmed: list[str] = []
        complete = True
        started_all = time.monotonic()
        for mode in self._modes:
            if not force and not self._cfg.rendering.prewarm_enabled:
                break
            try:
                provider = await self._provider_getter(mode)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"[HelpTypst] 预热 {mode} 构造数据流失败: {e}")
                complete = False
                continue
            if provider is None:
                continue

            started = time.monotonic()
            try:
                result, error = await self._renderer.render(provider, mode)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"[HelpTypst] 预热 {mode} 异常: {e}")
                complete = False
                continue
            if result is None:
                # 空结果 / 超时只影响预热, 用户请求时照常现编并自行提示
                logger.info(f"[HelpTypst] 预热 {mode} 未产出图片: {error}")
                complete = False
                continue
            warmed.append(mode)
            logger.info(
                f"[HelpTypst] 预热 {mode} 完成, 耗时 {time.monotonic() - started:.1f}s"
            )

        if warmed:
            logger.info(
                f"[HelpTypst] 预热结束 ({reason}): {'、'.join(warmed)}, "
                f"共 {time.monotonic() - started_all:.1f}s"
            )
        return warmed, complete
