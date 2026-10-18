from enum import Enum

from astrbot.core.star.star_handler import EventType


class _EventTypeLabelMap(dict[EventType, str]):
    """EventType → 事件监听分组标题

    未知事件类型统一回落「其他事件」: 上游会随版本新增 EventType (Agent/Tool 类),
    把英文枚举名直接展示给用户没有意义。覆盖 get() 的默认值, 消费方无需改动。
    """

    FALLBACK: str = "其他事件"

    def get(self, key: object, default: str | None = None) -> str:
        return super().get(key, self.FALLBACK)


# 事件类型映射表: (EventType 成员名, 中文分组标题)
# 按成员名动态取值, 低版本 AstrBot 缺失的成员自动跳过, 避免 import 期 AttributeError
_EVENT_TYPE_LABELS: tuple[tuple[str, str], ...] = (
    ("OnAstrBotLoadedEvent", "系统启动 (Loaded)"),
    ("OnPlatformLoadedEvent", "平台就绪 (Platform)"),
    ("AdapterMessageEvent", "消息监听 (Message)"),
    ("OnWaitingLLMRequestEvent", "等待 LLM 请求 (Wait-LLM)"),
    ("OnLLMRequestEvent", "LLM 请求前 (Pre-LLM)"),
    ("OnLLMResponseEvent", "LLM 响应后 (Post-LLM)"),
    ("OnAgentBeginEvent", "Agent 开始 (Agent)"),
    ("OnAgentDoneEvent", "Agent 完成 (Agent-Done)"),
    ("OnDecoratingResultEvent", "消息修饰 (Decorate)"),
    ("OnCallingFuncToolEvent", "函数工具调用 (Calling-Tool)"),
    ("OnUsingLLMToolEvent", "工具调用请求 (Using-Tool)"),
    ("OnLLMToolRespondEvent", "工具返回 (Tool-Respond)"),
    ("OnAfterMessageSentEvent", "发送回执 (Sent)"),
    ("OnPluginErrorEvent", "插件异常 (Plugin-Error)"),
    ("OnPluginLoadedEvent", "插件加载 (Plugin-Loaded)"),
    ("OnPluginUnloadedEvent", "插件卸载 (Plugin-Unloaded)"),
)


def _build_event_type_map() -> _EventTypeLabelMap:
    """构建事件类型映射 (成员缺失时跳过, 兼容低版本 AstrBot)"""
    mapping = _EventTypeLabelMap()
    for attr_name, label in _EVENT_TYPE_LABELS:
        event_type = getattr(EventType, attr_name, None)
        if isinstance(event_type, EventType):
            mapping[event_type] = label
    return mapping


class InternalCFG:
    """内部常量"""

    # 映射
    CACHE_FILES: dict[str, str] = {
        "command": "cache_menu_command",
        "command_detail": "cache_menu_command_detail",
        "event": "cache_menu_event",
        "filter": "cache_menu_filter",
    }

    EVENT_TYPE_MAP: _EventTypeLabelMap = _build_event_type_map()

    # 会引起布局变动的配置项 → 缓存失效
    CACHE_SENSITIVE_CONFIGS: list[str] = [
        "giant_threshold",
        "split_height",
        # 直接决定长图切片结果 (是否切、切成几张), 改动后必须重编
        "webp_limit",
        # 换发送格式 = 换产物扩展名, 旧格式文件必须让位
        "output_format",
        "ppi",
        # 页宽与单列阈值直接决定版式与出图像素, 改动后必须重编
        "page_width",
        "single_column_threshold",
        # 插件行双行模式改变行高与文本排布, 同样影响出图
        "plugin_two_lines",
        "ignored_plugins",
        "effective_colors",
        "header_background",
        "background_dir",
        "background_random",
        "hero_header",
        "category",
    ]

    # 发送图片格式 → 产物扩展名 (扩展名参与缓存文件命名, 换格式即换文件名)
    FORMAT_EXT: dict[str, str] = {
        "webp": ".webp",
        "png": ".png",
        "jpeg": ".jpg",
    }
    # 各格式单张边长上限: WebP 是硬限制 16383; PNG/JPEG 理论更大, 但再高 Pillow 解码/编码内存会失控,
    # 因此只放开到实用值, 超出部分仍按切片处理
    FORMAT_MAX_SIDE: dict[str, int] = {
        "webp": 16383,
        "png": 32000,
        "jpeg": 65500,
    }
    # 顶层相邻 block 之间的段间距 (Typst par.spacing = 1.2em, 正文 10pt)
    # 模板里用 measure 现算, 这里保存同一数值供图片裁剪对齐
    FLOW_GAP_PT = 12.0

    # 默认设计页宽: 三列布局 (事件/过滤器外栏、卡片内功能块/指令标签) 按该宽度排定,
    # 页宽再窄就退回两列, 避免每列被压到放不下标签/描述
    DESIGN_PAGE_WIDTH: float = 830.0

    # 头部背景图候选扩展名 (扫描背景目录时使用, 缓存文件按前缀排除)
    # 仅保留 Typst 可解码的栅格格式; 新增格式前先确认 Typst 支持
    BACKGROUND_IMAGE_EXTS: tuple[str, ...] = (
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".gif",
    )
    # 自动扫描时排除的缓存文件前缀
    BACKGROUND_IMAGE_EXCLUDE_PREFIXES: tuple[str, ...] = ("cache_", "temp_")

    # 文件/文件夹名
    NAME_TEMPLATE: str = "base.typ"
    NAME_FONT_DIR: str = "fonts"
    # 默认背景图目录 (数据目录下的子目录, 与字体目录一致)
    NAME_BACKGROUND_DIR: str = "backgrounds"

    # 时序
    DELAY_SEND: float = 1

    # 分类 (指令模式 /helps) 相关
    # 兜底分类名: 配置缺失/异常时的最终保底 (正常运行时使用 DefaultCFG.DEFAULT_CATEGORY_FALLBACK,
    # 用户可在设置面板通过 category.fallback 自定义, 详见 domain/config.py 的 CategoryConfig)
    CATEGORY_FALLBACK: str = "其他"
    # 默认分类关键词映射已迁移至 DefaultCFG.DEFAULT_CATEGORY_KEYWORDS (设置面板 category.rules 的预置默认值)
    # 两列高度估算系数 (pt): 只参与 utils/view.py 的分列决策, 不参与渲染。
    # 按 base.typ 的排版 (830pt 页宽、分类卡内边距、chip 字号) 折算, 并用真实渲染结果校准;
    # 页宽 / 字号 / 模板结构变化后需重新校准 (详见 utils/view.py 的 _estimate_category_height)。
    EST_CATEGORY_BASE: float = 42.0  # 指令模式: 分类卡片头部 + 列表内边距
    EST_CATEGORY_STACK_GAP: float = 12.0  # 分类卡片之间的 stack spacing
    EST_PLUGIN_ROW: float = 26.0  # 指令模式: 单个插件行 (含行距)
    EST_PLUGIN_NAME_WIDTH: float = 200.0  # 指令模式: 插件名可用宽度, 超出折行
    EST_PLUGIN_NAME_LINE: float = 14.0  # 插件名每多折一行的增量
    EST_DETAIL_CATEGORY_BASE: float = 50.0  # 详细模式: 分类卡片固定开销
    EST_DETAIL_PLUGIN_ROW: float = 40.0  # 详细模式: 插件条目头部行
    EST_DETAIL_CAPABILITY_BLOCK: float = 14.0  # 能力区: 分割线上下的留白
    EST_DETAIL_SECTION_LABEL: float = 20.0  # Commands / Listeners 小节标题
    EST_DETAIL_GROUP_OVERHEAD: float = 24.0  # 指令组容器: 内边距 + 组名
    EST_DETAIL_CHIP_ROW: float = 19.0  # 单行 chip 高度 (含行距)
    EST_DETAIL_CHIP_WIDTH: float = 356.0  # 插件条目内 chip 可用行宽
    EST_DETAIL_GROUP_CHIP_WIDTH: float = 350.0  # 指令组内 chip 可用行宽
    EST_CHIP_PADDING: float = 12.0  # chip 左右内边距 + 边框
    EST_CHIP_GAP: float = 3.0  # 相邻 chip 间距

    # 禁用插件灰化色板 (主题无关的固定值, 供 /helps 指令菜单灰化展示)
    DISABLED_COLORS: dict[str, str] = {
        "disabled_card_bg": "#F5F5F5",  # 禁用插件卡片背景 (极浅灰)
        "disabled_card_border": "#E7E7E7",  # 禁用插件卡片边框 (低对比灰)
        "disabled_badge_bg": "#D6C9CC",  # 编号徽章背景 (低饱和灰粉)
        "disabled_badge_text": "#9B8A8E",  # 编号徽章文字 (深灰粉, 保证可读)
        "disabled_name": "#B8B8B8",  # 插件名称 (浅灰)
        "disabled_cmd": "#C8C8C8",  # 命令名称/次级文本 (更浅灰)
        "disabled_icon": "#B9A5A8",  # 禁用图标 (圆圈 + 斜杠)
    }


class DefaultCFG:
    """兜底: 配置默认值"""

    # 1. 渲染限制
    LIMIT_TASK: int = 2  # 最大并发编译数
    LIMIT_GIANT: int = 1500
    LIMIT_WEBP: int = 16383
    LIMIT_SIDE: int = 16000
    # 发送图片格式: webp 体积最小, png 无损, jpeg 体积接近 webp
    OUTPUT_FORMAT: str = "webp"
    OUTPUT_FORMATS: tuple[str, ...] = ("webp", "png", "jpeg")
    # 单张高度上限/切片高度的配置上限: 按最大的 JPEG 放开, 实际执行时再按所选格式收敛
    MAX_LIMIT_SIDE: int = 65500
    # 与 _conf_schema.json 的 ppi 默认值一致: 144 / 180 都是历史默认值,
    # 当前面板与兜底统一为 256
    LIMIT_PPI: float = 256.0

    # 1.1 配置值收敛区间 (防御手工改坏的配置; 与设置面板 slider 范围对齐)
    MIN_PPI: float = 72.0
    # 上限受 WebP 单边 16383px 与 Pillow 像素上限约束: 600pt 页宽下 384ppi 已接近单张上限
    MAX_PPI: float = 384.0
    MIN_SPLIT_HEIGHT: int = 200  # image.py 按此高度切片, 过小无意义, 0 会除零
    # 页面总宽度 (pt): 越窄同 PPI 下出图越窄、文字相对越大, 聊天窗口里更易读
    LIMIT_WIDTH: float = 540.0
    # 页面宽度低于该值时改单列 (两列/三列在窄页宽下会挤成一团)
    LIMIT_SINGLE_COLUMN_THRESHOLD: float = 480.0
    # 360 是实测下限: Hero 统计卡 3×76pt + 26pt 左偏移占 274pt, 页面再窄 (≈330pt 以下) 就会溢出
    MIN_PAGE_WIDTH: float = 360.0
    MAX_PAGE_WIDTH: float = 1200.0
    # 插件双行模式: 英文 ID 移到中文名下方, 单行更窄, 窄页宽下不易被截断
    PLUGIN_TWO_LINES: bool = True
    MIN_WEBP_LIMIT: int = 1000
    MIN_GIANT: int = 100
    MAX_GIANT: int = 3000
    MIN_TIMEOUT_ANALYSIS: float = 1.0
    MIN_TIMEOUT_COMPILE: float = 3.0  # 与面板 slider min 一致
    MAX_TIMEOUT: float = 60.0
    MIN_CONCURRENCY: int = 1
    MAX_CONCURRENCY: int = 10

    # 2. 超时设置 (秒)
    TIMEOUT_ANALYSIS: float = 10.0
    TIMEOUT_COMPILE: float = 30.0

    # 3. 全局字体优先级 (appearance.font_order 缺省值)
    # 注意: 表情字体 (EMOJI_FONT) 不在此列, 由渲染时固定追加, 无需用户选择
    DEFAULT_FONT_ORDER: list[str] = ["LXGW Neo XiHei"]

    # 固定表情字体: 始终追加到最终字体列表末尾, 用于渲染 emoji 字形
    # 不出现在配置面板的字体选择项中 (用户无需也不应选择它)
    EMOJI_FONT: str = "Noto Color Emoji"

    # 系统字体目录映射 (扫描时并入选择框选项; ~ 在代码中展开)
    SYSTEM_FONT_DIRS: tuple[str, ...] = (
        # Windows
        "C:/Windows/Fonts",
        # macOS
        "/System/Library/Fonts",
        "/Library/Fonts",
        "~/Library/Fonts",
        # Linux
        "/usr/share/fonts",
        "/usr/local/share/fonts",
        "~/.fonts",
        "~/.local/share/fonts",
    )

    # 4. 过滤设置
    # config.py 负责 list → set
    IGNORED_PLUGINS: set[str] = {
        "astrbot",
        "astrbot-web-searcher",
        "astrbot-python-interpreter",
        "session_controller",
        "builtin_commands",
        "astrbot-reminder",
        "astrbot_plugin_help_typst",
        "astrbot_plugin_help_panel_typst",
    }

    # 5. 内置主题预设 (preset_name → 完整配色)
    # 每个配色字典含三类键:
    #   brand_*    : 品牌色板 (主色/结构色/背景/边框等, 13 个, 供指令菜单使用)
    #   cat_slot_N : 通用分类色槽 (0~9, 分类卡片标题栏取色, 分类规则按槽位绑定; 0 为兜底)
    #   c_*        : 通用颜色 (event/filter/detail 视图使用)

    # --- Ocean Blue 主题: 明亮清爽 (天蓝青 × 深海蓝 × 浅青蓝 × 奶油黄) ---
    OCEAN_BLUE_COLORS: dict[str, str] = {
        # 品牌色板
        "brand_sky": "#57CDE3",  # 天空蓝 · 第一主色
        "brand_navy": "#355A81",  # 深海蓝 · 结构色
        "brand_mint": "#8AE6E1",  # 浅青蓝 · 高光
        "brand_cream": "#FADE86",  # 奶油黄 · 强调
        "brand_gold": "#F0C14B",  # 金黄 · 暖强调
        "brand_blush": "#A8E9F2",  # 浅天蓝 · 柔和辅助
        "brand_ink": "#2E2E35",  # 深色
        "brand_gray": "#808E9D",  # 灰蓝 · 次级文字/disabled
        "brand_card": "#FFFFFF",  # 卡片背景
        "brand_border": "#DCEFF1",  # 卡片边框
        "brand_soft": "#E7EFF1",  # 插件行边框 (更浅)
        "brand_ghost": "#F3F6F7",  # disabled 行背景
        # 通用分类色槽 (cat_slot_0~9): 分类卡片标题栏统一取色源, 随主题切换变化
        # 槽位 0 = 兜底分类(其他) 默认色; 1~7 = AI/查询/工具/管理/娱乐/资讯/调试; 8~9 备用
        "cat_slot_0": "#808E9D",
        "cat_slot_1": "#57CDE3",
        "cat_slot_2": "#FADE86",
        "cat_slot_3": "#2E9BB8",
        "cat_slot_4": "#355A81",
        "cat_slot_5": "#8AE6E1",
        "cat_slot_6": "#A8E9F2",
        "cat_slot_7": "#6C8CA8",
        "cat_slot_8": "#F0C14B",
        "cat_slot_9": "#2E2E35",
        # 通用颜色
        "page_fill": "#F5FBFC",
        "c_plugin_name": "#355A81",
        "c_plugin_id": "#808E9D",
        "c_group_title": "#355A81",
        "c_bullet": "#57CDE3",
        "c_event_icon": "#F0C14B",
        "c_leaf_text": "#2E2E35",
        "c_desc_text": "#808E9D",
        "c_group_bg": "#E8F6F9",
        "c_rich_bg": "#FFFFFF",
        "c_box_bg": "#F3F6F7",
        "c_box_stroke": "#E7EFF1",
        "c_text_primary": "#355A81",
        "c_regex_bg": "#FFF6E3",
        "c_regex_text": "#C99114",
        "c_regex_icon": "#D4A017",
        "c_tag_admin": "#2E9BB8",
        "c_tag_event": "#F0C14B",
        "c_tag_mcp": "#355A81",
        "c_tag_id": "#355A81",
        "c_ver_bg": "#E8F6F9",
        "c_ver_text": "#355A81",
        "c_prio_bg": "#FDF6DC",
        "c_prio_text": "#C99114",
        "c_highlight_bg": "#FADE86",
        "c_highlight_text": "#2E2E35",
        "c_on_light": "#355A81",
    }

    # --- Night Navy 主题: 深邃夜幕 (深色科技感, 青黄霓虹) ---
    NIGHT_NAVY_COLORS: dict[str, str] = {
        # 品牌色板
        "brand_sky": "#57CDE3",  # 天空蓝 · 霓虹高光
        "brand_navy": "#D8E6F5",  # 主文字色 (深底用浅色)
        "brand_mint": "#8AE6E1",  # 浅青蓝 · 发光边
        "brand_cream": "#FFE08A",  # 奶油黄 · 点睛
        "brand_gold": "#FFD54A",  # 金黄 · 强调
        "brand_blush": "#B7E9F5",  # 亮青 · 柔和辅助
        "brand_ink": "#E6EEF5",  # 正文文字 (浅色)
        "brand_gray": "#8AA0B8",  # 次级文字
        "brand_card": "#1B3048",  # 卡片背景 (深)
        "brand_border": "#2E4560",  # 卡片边框
        "brand_soft": "#243C54",  # 插件行边框
        "brand_ghost": "#16283E",  # disabled 行背景
        # 通用分类色槽 (cat_slot_0~9): 槽位 0=兜底, 1~7=默认分类, 8~9 备用
        "cat_slot_0": "#6B88A3",
        "cat_slot_1": "#57CDE3",
        "cat_slot_2": "#FFE08A",
        "cat_slot_3": "#4A7FB5",
        "cat_slot_4": "#1F3A5F",
        "cat_slot_5": "#8AE6E1",
        "cat_slot_6": "#A8D8F0",
        "cat_slot_7": "#5B7EA3",
        "cat_slot_8": "#FFD54A",
        "cat_slot_9": "#C084FC",
        # 通用颜色
        "page_fill": "#0E1E31",
        "c_plugin_name": "#D8E6F5",
        "c_plugin_id": "#8AA0B8",
        "c_group_title": "#D8E6F5",
        "c_bullet": "#57CDE3",
        "c_event_icon": "#FFD54A",
        "c_leaf_text": "#E6EEF5",
        "c_desc_text": "#8AA0B8",
        "c_group_bg": "#1B3048",
        "c_rich_bg": "#1B3048",
        "c_box_bg": "#16283E",
        "c_box_stroke": "#2E4560",
        "c_text_primary": "#D8E6F5",
        "c_regex_bg": "#243C54",
        "c_regex_text": "#FFE08A",
        "c_regex_icon": "#FFD54A",
        "c_tag_admin": "#8AE6E1",
        "c_tag_event": "#FFD54A",
        "c_tag_mcp": "#57CDE3",
        "c_tag_id": "#8AA0B8",
        "c_ver_bg": "#243C54",
        "c_ver_text": "#8AE6E1",
        "c_prio_bg": "#243C54",
        "c_prio_text": "#FFE08A",
        "c_highlight_bg": "#2E5A8A",
        "c_highlight_text": "#FFFFFF",
        "c_on_light": "#10233A",
    }

    # --- Soft Mist 主题: 柔和晨雾 (莫兰迪低饱和) ---
    SOFT_MIST_COLORS: dict[str, str] = {
        # 品牌色板
        "brand_sky": "#8FC6D8",  # 天空蓝加灰 · 主色
        "brand_navy": "#5C7086",  # 深海蓝加灰 · 结构色
        "brand_mint": "#A8DCD8",  # 浅青加灰 · 高光
        "brand_cream": "#E5D3A8",  # 奶油黄加灰 · 强调
        "brand_gold": "#D9BE7E",  # 金黄加灰
        "brand_blush": "#C4D8E0",  # 淡蓝灰 · 柔和辅助
        "brand_ink": "#3C4652",  # 深灰蓝
        "brand_gray": "#8A98A6",  # 灰 · 次级文字
        "brand_card": "#FFFFFF",  # 卡片背景
        "brand_border": "#D7E6EC",  # 卡片边框
        "brand_soft": "#E2EBEF",  # 插件行边框
        "brand_ghost": "#EEF2F4",  # disabled 行背景
        # 通用分类色槽 (cat_slot_0~9): 槽位 0=兜底, 1~7=默认分类, 8~9 备用
        "cat_slot_0": "#8A98A6",
        "cat_slot_1": "#8FC6D8",
        "cat_slot_2": "#E5D3A8",
        "cat_slot_3": "#6FA3B8",
        "cat_slot_4": "#5C7086",
        "cat_slot_5": "#A8DCD8",
        "cat_slot_6": "#B0C6D4",
        "cat_slot_7": "#7A8FA6",
        "cat_slot_8": "#D9BE7E",
        "cat_slot_9": "#3C4652",
        # 通用颜色
        "page_fill": "#F2F7F9",
        "c_plugin_name": "#5C7086",
        "c_plugin_id": "#8A98A6",
        "c_group_title": "#5C7086",
        "c_bullet": "#8FC6D8",
        "c_event_icon": "#D9BE7E",
        "c_leaf_text": "#3C4652",
        "c_desc_text": "#8A98A6",
        "c_group_bg": "#E6EEF2",
        "c_rich_bg": "#FFFFFF",
        "c_box_bg": "#EEF2F4",
        "c_box_stroke": "#E2EBEF",
        "c_text_primary": "#5C7086",
        "c_regex_bg": "#F4EEE0",
        "c_regex_text": "#8A7430",
        "c_regex_icon": "#A08A50",
        "c_tag_admin": "#6FA3B8",
        "c_tag_event": "#D9BE7E",
        "c_tag_mcp": "#5C7086",
        "c_tag_id": "#5C7086",
        "c_ver_bg": "#E6EEF2",
        "c_ver_text": "#5C7086",
        "c_prio_bg": "#F0EAD8",
        "c_prio_text": "#8A7430",
        "c_highlight_bg": "#E5D3A8",
        "c_highlight_text": "#3C4652",
        "c_on_light": "#3C4652",
    }

    # --- Vivid Pop 主题: 活力跃动 (高饱和冲击) ---
    VIVID_POP_COLORS: dict[str, str] = {
        # 品牌色板
        "brand_sky": "#22C8E8",  # 亮天蓝 · 主色
        "brand_navy": "#1E3A7A",  # 藏青 · 结构色
        "brand_mint": "#2FE0D0",  # 鲜薄荷青 · 高光
        "brand_cream": "#FFD54A",  # 亮金黄 · 强调
        "brand_gold": "#FFC400",  # 金黄
        "brand_blush": "#B3F0FA",  # 亮青 · 柔和辅助
        "brand_ink": "#1A2438",  # 深墨蓝
        "brand_gray": "#7C8AA0",  # 蓝灰 · 次级文字
        "brand_card": "#FFFFFF",  # 卡片背景
        "brand_border": "#D8F0F8",  # 卡片边框
        "brand_soft": "#E3F3F9",  # 插件行边框
        "brand_ghost": "#F1F8FB",  # disabled 行背景
        # 通用分类色槽 (cat_slot_0~9): 槽位 0=兜底, 1~7=默认分类, 8~9 备用
        "cat_slot_0": "#7C8AA0",
        "cat_slot_1": "#22C8E8",
        "cat_slot_2": "#FFD54A",
        "cat_slot_3": "#4A90E2",
        "cat_slot_4": "#1E3A7A",
        "cat_slot_5": "#2FE0D0",
        "cat_slot_6": "#B3F0FA",
        "cat_slot_7": "#5B7DB5",
        "cat_slot_8": "#FF5252",
        "cat_slot_9": "#1A2438",
        # 通用颜色
        "page_fill": "#F2FBFF",
        "c_plugin_name": "#1E3A7A",
        "c_plugin_id": "#7C8AA0",
        "c_group_title": "#1E3A7A",
        "c_bullet": "#22C8E8",
        "c_event_icon": "#FFC400",
        "c_leaf_text": "#1A2438",
        "c_desc_text": "#7C8AA0",
        "c_group_bg": "#E3F7FD",
        "c_rich_bg": "#FFFFFF",
        "c_box_bg": "#F1F8FB",
        "c_box_stroke": "#E3F3F9",
        "c_text_primary": "#1E3A7A",
        "c_regex_bg": "#FFF4D6",
        "c_regex_text": "#B8860B",
        "c_regex_icon": "#E6A800",
        "c_tag_admin": "#4A90E2",
        "c_tag_event": "#FFC400",
        "c_tag_mcp": "#1E3A7A",
        "c_tag_id": "#1E3A7A",
        "c_ver_bg": "#E3F7FD",
        "c_ver_text": "#1E3A7A",
        "c_prio_bg": "#FFF0C2",
        "c_prio_text": "#B8860B",
        "c_highlight_bg": "#FFD54A",
        "c_highlight_text": "#1A2438",
        "c_on_light": "#1E3A7A",
    }

    # --- zhenxun 主题: 柔和马卡龙粉彩 ---
    ZHENXUN_COLORS: dict[str, str] = {
        # 品牌色板
        "brand_sky": "#F36F88",  # 粉 · 第一主色
        "brand_navy": "#3A3A3A",  # 结构色 · 深灰
        "brand_mint": "#F7C8D0",  # 浅粉
        "brand_cream": "#FADE86",  # 奶油黄
        "brand_gold": "#FFB84D",  # 橙
        "brand_blush": "#E1BEE7",  # 浅紫
        "brand_ink": "#2B2B2B",  # 深色
        "brand_gray": "#9E9E9E",  # 灰 · 次级文字/disabled
        "brand_card": "#FFFFFF",  # 卡片背景
        "brand_border": "#ECE9E4",  # 卡片边框
        "brand_soft": "#F0EDE8",  # 插件行边框
        "brand_ghost": "#F6F5F3",  # disabled 行背景
        # 通用分类色槽 (cat_slot_0~9): 槽位 0=兜底, 1~7=默认分类, 8~9 备用
        "cat_slot_0": "#4DB5AD",
        "cat_slot_1": "#F16B86",
        "cat_slot_2": "#A8D77A",
        "cat_slot_3": "#FFB84D",
        "cat_slot_4": "#B45BC5",
        "cat_slot_5": "#4DBCE8",
        "cat_slot_6": "#E97878",
        "cat_slot_7": "#F36F88",
        "cat_slot_8": "#E1BEE7",
        "cat_slot_9": "#FADE86",
        # 通用颜色
        "page_fill": "#FAF9F7",
        "c_plugin_name": "#0d47a1",
        "c_plugin_id": "#546e7a",
        "c_group_title": "#6a1b9a",
        "c_bullet": "#F36F88",
        "c_event_icon": "#ffc72c",
        "c_leaf_text": "#37474f",
        "c_desc_text": "#9e9e9e",
        "c_group_bg": "#f3e5f5",
        "c_rich_bg": "#fcfcfc",
        "c_box_bg": "#f6f5f3",
        "c_box_stroke": "#ece9e4",
        "c_text_primary": "#2b2b2b",
        "c_regex_bg": "#fff3e0",
        "c_regex_text": "#e65100",
        "c_regex_icon": "#f57c00",
        "c_tag_admin": "#c62828",
        "c_tag_event": "#f57c00",
        "c_tag_mcp": "#00695c",
        "c_tag_id": "#283593",
        "c_ver_bg": "#e3f2fd",
        "c_ver_text": "#1565c0",
        "c_prio_bg": "#e8eaf6",
        "c_prio_text": "#283593",
        "c_highlight_bg": "#ffeb3b",
        "c_highlight_text": "#000000",
        "c_on_light": "#3A3A3A",
    }

    # 预设注册表 (preset_name → 配色), 供 config.py 内置注册
    PRESETS: dict[str, dict[str, str]] = {
        "Ocean Blue": OCEAN_BLUE_COLORS,
        "Night Navy": NIGHT_NAVY_COLORS,
        "Soft Mist": SOFT_MIST_COLORS,
        "Vivid Pop": VIVID_POP_COLORS,
        "zhenxun": ZHENXUN_COLORS,
    }

    # 6. 插件分类规则 (指令模式 /helps 分类卡片)
    # 默认分类关键词映射: 作为设置面板 category.rules 的预置默认值导入, 用户可自由增删改。
    # 列表顺序即匹配优先级 (命中第一个匹配的分类即归入), 全部未命中时归入兜底分类。
    DEFAULT_CATEGORY_KEYWORDS: dict[str, list[str]] = {
        "AI": [
            "llm",
            "模型",
            "gpt",
            "大模型",
            "对话",
            "智能",
            "画图",
            "绘图",
            "文生图",
            "图像",
            "绘画",
            "image",
            "diffusion",
        ],
        "查询": [
            "查询",
            "搜索",
            "百科",
            "词典",
            "翻译",
            "天气",
            "汇率",
            "快递",
            "新闻",
            "热搜",
            "日历",
            "黄历",
            "search",
            "query",
            "wiki",
            "translate",
            "weather",
        ],
        "工具": [
            "工具",
            "计算",
            "转换",
            "二维码",
            "短链",
            "短网址",
            "解析",
            "压缩",
            "编码",
            "tool",
            "qrcode",
            "聚合",
            "网盘",
        ],
        "管理": [
            "管理",
            "群管",
            "禁言",
            "踢人",
            "审核",
            "权限",
            "撤回",
            "违禁词",
            "黑名单",
            "风控",
            "admin",
        ],
        "娱乐": [
            "娱乐",
            "游戏",
            "抽奖",
            "点歌",
            "音乐",
            "笑话",
            "梗图",
            "表情包",
            "随机",
            "运势",
            "签到",
            "塔罗",
            "占卜",
            "骰子",
            "game",
            "music",
        ],
        "资讯": [
            "资讯",
            "订阅",
            "推送",
            "通知",
            "提醒",
            "播报",
            "监控",
            "rss",
            "news",
            "feed",
        ],
        "调试": [
            "调试",
            "开发",
            "测试",
            "日志",
            "诊断",
            "debug",
            "dev",
        ],
    }

    # 兜底分类名 (设置面板 category.fallback 的缺省值; 与 InternalCFG.CATEGORY_FALLBACK 保持一致)
    DEFAULT_CATEGORY_FALLBACK: str = InternalCFG.CATEGORY_FALLBACK

    # 兜底分类颜色 (设置面板 category.fallback_color 的缺省值): 绑定主题色槽 slot_0
    # (槽位 0 即原「其他」分类色, 随主题切换变化; 用户可改为其它 slot_N 或固定 #RRGGBB)
    DEFAULT_CATEGORY_FALLBACK_COLOR: str = "slot_0"

    # 默认分类 → 主题色槽绑定 (预置规则随默认配置导入, 用户可自由修改):
    # 与各主题 cat_slot_1~7 的槽位顺序一致, 保证 zhenxun 主题下默认分类保持原配色
    DEFAULT_CATEGORY_SLOT_BINDINGS: dict[str, str] = {
        "AI": "slot_1",
        "查询": "slot_2",
        "工具": "slot_3",
        "管理": "slot_4",
        "娱乐": "slot_5",
        "资讯": "slot_6",
        "调试": "slot_7",
    }

    # 默认主题色槽 (zhenxun 的 cat_slot_0~9): 主题未定义任何色槽时的兜底色板
    # (类体内不能用推导式引用类属性, 故用普通循环)
    DEFAULT_CATEGORY_SLOTS: list[str] = []
    for _slot_i in range(0, 10):
        DEFAULT_CATEGORY_SLOTS.append(ZHENXUN_COLORS[f"cat_slot_{_slot_i}"])

    # 默认激活的预设名
    DEFAULT_PRESET: str = "zhenxun"

    # 下拉框中的「自定义」选项 (对应下方 presets 列表中的自定义配置)
    CUSTOM_PRESET_KEY: str = "自定义"

    # 向后兼容: DEFAULT_COLORS 指向默认预设配色
    DEFAULT_COLORS: dict[str, str] = ZHENXUN_COLORS


class RenderMode(str, Enum):
    """历史遗留枚举

    当前调度使用字符串 mode, 以 InternalCFG.CACHE_FILES 为准; 本枚举仅作旧代码兼容,
    新增渲染模式不要只改这里 (还需登记 CACHE_FILES 等, 见 AGENTS §5.4)。
    """

    COMMAND = "command"
    COMMAND_DETAIL = "command_detail"
    EVENT = "event"
    FILTER = "filter"
