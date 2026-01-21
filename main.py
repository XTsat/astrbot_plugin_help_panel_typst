import asyncio
from pathlib import Path

from astrbot.api import logger, AstrBotConfig
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, StarTools
from astrbot.api.message_components import Image

from .domain import InternalCFG, TypstPluginConfig
from .utils import FontManager, HelpHint, MsgRecall, TypstLayout
from .core import CommandAnalyzer, EventAnalyzer, FilterAnalyzer, TypstRenderer


class HelpTypst(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        # 1. 静态资源路径
        self.plugin_dir = Path(__file__).parent
        self.data_dir = StarTools.get_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.template_path = self.plugin_dir / "templates" / InternalCFG.NAME_TEMPLATE
        self.schema_path = self.plugin_dir / "_conf_schema.json"

        # 2. 配置加载
        self.config = config
        self.plugin_config = TypstPluginConfig.load(config)
        
        # 3. 获取字体
        raw_path = self.plugin_config.custom_font_path
        if raw_path and raw_path.strip():
            self.user_font_dir = Path(raw_path)          # 自定义字体目录
        else:
            self.user_font_dir = self.data_dir / "fonts" # 缺省值

        try:
            self.user_font_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            if not raw_path: 
                logger.warning(f"[HelpTypst] 无法创建默认字体目录: {e}")

        self.builtin_font_dir = self.plugin_dir / "resources" / InternalCFG.NAME_FONT_DIR # 内置
        self.font_dirs = [self.builtin_font_dir, self.user_font_dir]                      # 汇总

        # 3. 初始化组件
        self.font_manager = FontManager(self.font_dirs)
        self.layout = TypstLayout(self.plugin_config)
        self.hint = HelpHint()
        self.msg = MsgRecall()

        # 4. 渲染器
        self.renderer = TypstRenderer(
            star=self,
            data_dir=self.data_dir,
            template_path=self.template_path,
            font_dirs=self.font_dirs,
            config=self.plugin_config,
        )

        # 5. 分析器
        self.cmd_analyzer = CommandAnalyzer(context, self.plugin_config)
        self.evt_analyzer = EventAnalyzer(context, self.plugin_config)
        self.flt_analyzer = FilterAnalyzer(context, self.plugin_config)

        self.prefixes: list[str] = []

    async def initialize(self):
        """异步初始化"""
        self._init_prefixes(self.context)
        await asyncio.to_thread(self._refresh_resources)
        logger.info("[HelpTypst] 初始化完成")
    
    def _refresh_resources(self):
        try:
            # 1. 扫描
            self.font_manager.scan_fonts()

            # 2. 更新 Schema
            self.font_manager.update_json_schema(self.schema_path)

            # 3. 清洗 Config
            self.font_manager.prune_invalid_config_items(self.config)

        except Exception as e:
            logger.warning(f"[HelpTypst] 资源重载失败: {e}")

    async def terminate(self):
        """周期hook"""
        # 1. 清理临时文件
        await self._perform_cleanup()

        # 2. [Dirty Hook] 刷新 Schema
        # 用需重载维护的 Optional: 因为 勾选 + 排序 是 字体优先级 操作逻辑上的最佳实践
        # 时序: 配置页面构建于插件实例化之前, 这是自动维护的最佳时点
        # 阻塞: 符合预期，这是确保 放入/删除字体 → 重载即可见 的必要代价
        try:
            self._refresh_resources()
        except Exception:
            pass

    async def _perform_cleanup(self):
        try:
            # glob 匹配
            temp_files = list(self.data_dir.glob("temp_*"))
            if not temp_files:
                return

            logger.debug(f"[HelpTypst] 清理 {len(temp_files)} 个缓存文件...")
            
            for f in temp_files:
                try:
                    if f.exists(): # 双重检查
                        f.unlink()
                except OSError:
                    pass

        except Exception as e:
            logger.warning(f"[HelpTypst] 清理失败: {e}")

    @filter.command_group("typst")  # 该指令组留待扩展更多调试功能
    @filter.permission_type(filter.PermissionType.ADMIN)
    def typst(self):
        pass

    @typst.command("font")
    async def cmd_scan_fonts(self, event: AstrMessageEvent):
        """扫描字体并重载插件"""
        # 1. 扫描与更新
        await asyncio.to_thread(self._refresh_resources)
        count = len(self.font_manager.available_families)

        # 2. 尝试自我重载
        try:
            pm = getattr(
                self.context, "_star_manager", None
            )  # hack: 获取 PluginManager 实例
            if pm:
                plugin_name = getattr(self, "name", "astrbot_plugin_help_typst")
                yield event.plain_result(
                    f"✅ 扫描完成 ({count} fonts)。正在重载以刷新面板..."
                )
                asyncio.create_task(self._safe_reload(pm, plugin_name))  # 异步延迟重载
            else:
                yield event.plain_result(f"✅ 扫描完成 ({count} fonts)。请手动重载插件")
        except Exception as e:
            yield event.plain_result(f"❌ 自动重载失败: {e}")

    async def _safe_reload(self, pm, plugin_name):
        """延迟重载"""
        await asyncio.sleep(InternalCFG.DELAY_SEND)
        try:
            logger.info(f"[HelpTypst] 正在执行自我重载: {plugin_name}")
            await pm.reload(plugin_name)
        except Exception as e:
            logger.error(f"[HelpTypst] 自我重载异常: {e}")

    async def _handle_request(
        self,
        event: AstrMessageEvent,
        analyzer,
        title: str,
        mode: str,
        query: str | None,
    ):
        """通用请求处理逻辑"""
        wait_msg_id = None

        if self.plugin_config.enable_waiting_message:
            # 1. 发送提示
            hint_text = (
                self.hint.msg_searching(query) if query else self.hint.msg_rendering(mode)
            )
            wait_msg_id = await self.msg.send_wait(event, hint_text)

        def data_pipeline(save_path: Path) -> int:
            """数据流转"""
            # 数据层：获取对象
            plugins = analyzer.get_plugins(query)
            if not plugins:
                return 0

            # 视图层：决定标题 & 计算布局 & 写入JSON
            display_title = f'搜索结果: "{query}"' if query else title
            user_fonts = (
                self.plugin_config.appearance.get_active_font_order()
            )  # 预设字体配置
            final_font_list = self.font_manager.get_render_font_list(user_fonts)  # 校验

            self.layout.dump_layout_json(
                plugins=plugins,
                save_path=save_path,
                title=display_title,
                mode=mode,
                prefixes=self.prefixes,
                font_list=final_font_list,
            )

            return len(plugins)

        # 2. 执行渲染
        result, error = await self.renderer.render(data_pipeline, mode, query)

        # 3. 结束撤回提示
        if wait_msg_id:
            await self.msg.recall(event, wait_msg_id)

        # 4. 处理结果
        if result:
            try:
                yield event.chain_result([Image.fromFileSystem(p) for p in result.images])
            finally:
                # 后台任务清理文件列表
                if result.temp_files:
                    asyncio.create_task(self._cleanup_task(result.temp_files))
        else:
            # 错误处理
            if error == "empty":
                yield event.plain_result(self.hint.msg_empty_result(mode, query))
            else:
                yield event.plain_result(error)

    async def _cleanup_task(self, files: list[Path]):
        """异步清理任务"""
        await asyncio.sleep(InternalCFG.DELAY_SEND)
        for p in files:
            try:
                if p.exists():
                    p.unlink()
            except Exception as e:
                logger.warning(f"[HelpTypst] 临时文件清理失败 {p}: {e}")

    def _init_prefixes(self, context: Context):
        """唤醒词"""
        try:
            global_config = context.get_config()
            raw = global_config.get("wake_prefix", ["/"])
            self.prefixes = [raw] if isinstance(raw, str) else list(raw)
        except Exception as e:
            logger.warning(f"[HelpTypst] 获取唤醒词失败，使用默认值 '/': {e}")
            self.prefixes = ["/"]

    @filter.command("helps")
    async def show_menu(self, event: AstrMessageEvent, query: str = ""):
        """显示指令菜单"""
        async for r in self._handle_request(
            event, self.cmd_analyzer, "AstrBot 指令菜单", "command", query
        ):
            yield r

    @filter.command("events")
    async def show_events(self, event: AstrMessageEvent, query: str = ""):
        """显示事件监听列表"""
        async for r in self._handle_request(
            event, self.evt_analyzer, "AstrBot 事件监听", "event", query
        ):
            yield r

    @filter.command("filters")
    async def show_filters(self, event: AstrMessageEvent, query: str = ""):
        """显示过滤器详情"""
        async for r in self._handle_request(
            event, self.flt_analyzer, "AstrBot 过滤器分析", "filter", query
        ):
            yield r
