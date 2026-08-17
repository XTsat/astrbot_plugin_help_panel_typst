from enum import Enum

from astrbot.core.star.star_handler import EventType


class InternalCFG:
    """内部常量"""

    # 映射
    CACHE_FILES: dict[str, str] = {
        "command": "cache_menu_command",
        "event": "cache_menu_event",
        "filter": "cache_menu_filter",
    }

    EVENT_TYPE_MAP: dict[EventType, str] = {
        EventType.OnAstrBotLoadedEvent: "系统启动 (Loaded)",
        EventType.OnPlatformLoadedEvent: "平台就绪 (Platform)",
        EventType.AdapterMessageEvent: "消息监听 (Message)",
        EventType.OnLLMRequestEvent: "LLM 请求前 (Pre-LLM)",
        EventType.OnLLMResponseEvent: "LLM 响应后 (Post-LLM)",
        EventType.OnDecoratingResultEvent: "消息修饰 (Decorate)",
        EventType.OnAfterMessageSentEvent: "发送回执 (Sent)",
    }

    # 会引起布局变动的配置项 → 缓存失效
    CACHE_SENSITIVE_CONFIGS: list[str] = [
        "giant_threshold",
        "split_height",
        "ppi",
        "ignored_plugins",
        "effective_colors",
    ]

    # 文件/文件夹名
    NAME_TEMPLATE: str = "base.typ"
    NAME_FONT_DIR: str = "fonts"

    # 时序
    DELAY_SEND: float = 1

    # 分类 (指令模式 /helps) 相关
    # 兜底分类名, 匹配不到任何关键词时使用
    CATEGORY_FALLBACK: str = "其他"
    # 分类关键词映射: 插入顺序即匹配优先级, 命中即返回
    CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
        "查询": (
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
        ),
        "娱乐": (
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
        ),
        "工具": (
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
        ),
        "管理": (
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
            "ban",
        ),
        "资讯": (
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
        ),
        "AI": (
            "ai",
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
        ),
        "调试": (
            "调试",
            "开发",
            "测试",
            "日志",
            "诊断",
            "debug",
            "dev",
        ),
    }
    # 分类卡片布局估算 (pt): 仅用于 2 列平衡, 与模板 category_card 的 spacing 保持近似
    # 每张卡片在列内占用的高度 ≈ HEADER + ROW * 插件数 (HEADER 已含彩色头部、列表 padding、边框阴影与卡片间距)
    CATEGORY_HEADER_HEIGHT: int = 70
    # 单个插件盒子(含盒子间距 8pt) 的高度
    CATEGORY_ROW_HEIGHT: int = 36

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
    LIMIT_PPI: float = 144.0

    # 2. 超时设置 (秒)
    TIMEOUT_ANALYSIS: float = 10.0
    TIMEOUT_COMPILE: float = 30.0

    # 3. 全局字体优先级 (appearance.font_order 缺省值)
    DEFAULT_FONT_ORDER: list[str] = ["LXGW Neo XiHei", "Noto Color Emoji"]

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
    }

    # 5. 内置主题预设 (preset_name → 完整配色)
    # 每个配色字典含三类键:
    #   brand_* : 品牌色板 (主色/结构色/背景/边框等, 13 个, 供指令菜单使用)
    #   cat_*   : 分类主题色 (按分类名, 供分类卡片标题栏使用)
    #   c_*     : 通用颜色 (event/filter/detail 视图使用)

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
        # 分类主题色
        "cat_AI": "#57CDE3",
        "cat_工具": "#2E9BB8",
        "cat_管理": "#355A81",
        "cat_娱乐": "#8AE6E1",
        "cat_查询": "#FADE86",
        "cat_其他": "#808E9D",
        "cat_资讯": "#A8E9F2",
        "cat_调试": "#6C8CA8",
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
        # 分类主题色
        "cat_AI": "#57CDE3",
        "cat_工具": "#4A7FB5",
        "cat_管理": "#1F3A5F",
        "cat_娱乐": "#8AE6E1",
        "cat_查询": "#FFE08A",
        "cat_其他": "#6B88A3",
        "cat_资讯": "#A8D8F0",
        "cat_调试": "#5B7EA3",
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
        # 分类主题色
        "cat_AI": "#8FC6D8",
        "cat_工具": "#6FA3B8",
        "cat_管理": "#5C7086",
        "cat_娱乐": "#A8DCD8",
        "cat_查询": "#E5D3A8",
        "cat_其他": "#8A98A6",
        "cat_资讯": "#B0C6D4",
        "cat_调试": "#7A8FA6",
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
        # 分类主题色
        "cat_AI": "#22C8E8",
        "cat_工具": "#4A90E2",
        "cat_管理": "#1E3A7A",
        "cat_娱乐": "#2FE0D0",
        "cat_查询": "#FFD54A",
        "cat_其他": "#7C8AA0",
        "cat_资讯": "#B3F0FA",
        "cat_调试": "#5B7DB5",
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
        # 分类主题色
        "cat_AI": "#F16B86",
        "cat_工具": "#FFB84D",
        "cat_管理": "#B45BC5",
        "cat_娱乐": "#4DBCE8",
        "cat_查询": "#A8D77A",
        "cat_其他": "#4DB5AD",
        "cat_资讯": "#E97878",
        "cat_调试": "#F36F88",
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

    # 默认激活的预设名
    DEFAULT_PRESET: str = "Ocean Blue"

    # 下拉框中的「自定义」选项 (对应下方 presets 列表中的自定义配置)
    CUSTOM_PRESET_KEY: str = "自定义"

    # 向后兼容: DEFAULT_COLORS 指向默认预设配色
    DEFAULT_COLORS: dict[str, str] = OCEAN_BLUE_COLORS


class RenderMode(str, Enum):
    """枚举"""

    COMMAND = "command"
    EVENT = "event"
    FILTER = "filter"
