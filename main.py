import asyncio
from pathlib import Path

from astrbot.api import logger, AstrBotConfig
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, StarTools
import astrbot.api.message_components as Comp

from .domain import InternalCFG
from .utils import TypstPluginConfig
from .core import CommandAnalyzer, EventAnalyzer, FilterAnalyzer, TypstRenderer

class AsyncNullContext: # 异步空上下文
    async def __aenter__(self):
        return None
    async def __aexit__(self, exc_type, exc_value, traceback):
        return None

class HelpTypst(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        
        # 1. 配置加载
        # 将原始字典配置转换为强类型的 Dataclass 配置对象
        self.plugin_config = TypstPluginConfig.load(config)

        # 2. 基础路径初始化
        self.plugin_dir = Path(__file__).parent
        self.data_dir = StarTools.get_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        template_path = self.plugin_dir / "templates" / InternalCFG.TEMPLATE_NAME
        font_dir = self.plugin_dir / "resources" / InternalCFG.FONT_DIR_NAME

        # 3. 初始化渲染引擎 (Renderer)
        # 将路径资源和渲染相关的配置 (RenderingConfig) 注入
        self.renderer = TypstRenderer(
            data_dir=self.data_dir,
            template_path=template_path,
            font_dir=font_dir,
            config=self.plugin_config.rendering
        )
        
        # 4. 初始化分析器 (Analyzer)
        self.cmd_analyzer = CommandAnalyzer(context, self.plugin_config)
        self.evt_analyzer = EventAnalyzer(context, self.plugin_config)
        self.flt_analyzer = FilterAnalyzer(context, self.plugin_config)

    async def _handle_request(self, event: AstrMessageEvent, analyzer, title: str, mode: str, query: str | None):
        """通用请求处理逻辑"""
        if query:
            yield event.plain_result(f"正在搜索 '{query}'...")
        else:
            yield event.plain_result("正在渲染..." if mode == "command" else "正在获取列表...")

        # 定义数据获取回调 (延迟执行)
        def data_provider(save_path: Path) -> int:
            return analyzer.generate_render_data(save_path, title=title, mode=mode, query=query)

        # 调用渲染引擎
        result, error = await self.renderer.render(data_provider, mode, query)

        # 处理结果
        if result:
            try:
                # 构建消息链
                comps = [Comp.Image.fromFileSystem(p) for p in result.images]
                yield event.chain_result(comps)
            finally:
                # 只有临时文件需要在此处清理
                # Renderer 返回的 result.temp_files 包含了需要清理的文件列表
                if result.temp_files:
                    # 启动后台任务清理，不阻塞发送
                    asyncio.create_task(self._cleanup_task(result.temp_files))
        else:
            # 错误处理
            if error == "empty":
                target = "事件监听器" if mode == "event" else "插件或指令"
                msg = f"未找到包含 '{query}' 的{target}。" if query else f"当前没有可显示的{target}。"
                yield event.plain_result(msg)
            else:
                yield event.plain_result(error)

    async def _cleanup_task(self, files: list[Path]):
        """异步清理任务"""
        await asyncio.sleep(1) # 稍作等待确保发送完成
        for p in files:
            try:
                if p.exists(): p.unlink()
            except Exception as e:
                logger.warning(f"[HelpTypst] 临时文件清理失败 {p}: {e}")

    def _parse_query(self, event: AstrMessageEvent) -> str | None:
        parts = event.message_str.strip().split(maxsplit=1)
        return parts[1].strip() if len(parts) > 1 else None

    @filter.command("helps")
    async def show_menu(self, event: AstrMessageEvent):
        """显示指令菜单"""
        query = self._parse_query(event)
        async for r in self._handle_request(event, self.cmd_analyzer, "AstrBot 指令菜单", "command", query):
            yield r

    @filter.command("events")
    async def show_events(self, event: AstrMessageEvent):
        """显示事件监听列表"""
        query = self._parse_query(event)
        async for r in self._handle_request(event, self.evt_analyzer, "AstrBot 事件监听", "event", query):
            yield r

    @filter.command("filters")
    async def show_filters(self, event: AstrMessageEvent):
        """显示过滤器详情"""
        query = self._parse_query(event)
        async for r in self._handle_request(event, self.flt_analyzer, "AstrBot 过滤器分析", "filter", query):
            yield r

    async def terminate(self):
        """插件卸载时清理"""
        try:
            for f in self.data_dir.glob("temp_*"):
                try: f.unlink()
                except: pass
        except Exception: pass