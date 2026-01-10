from enum import Enum
from typing import Set, Dict

from astrbot.core.star.star_handler import EventType

class InternalCFG:
    """内部常量"""
    # 映射
    CACHE_FILES: Dict[str, str] = {
        "command": "cache_menu_command",
        "event":   "cache_menu_event",
        "filter":  "cache_menu_filter"
    }

    EVENT_TYPE_MAP: Dict[EventType, str] = {
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
        "ppi"
    ]

    # 文件/文件夹名
    NAME_TEMPLATE: str = "base.typ"
    NAME_FONT_DIR: str = "fonts"

    # 时序
    DELAY_SEND: float = 1


class DefaultCFG:
    """兜底: 配置默认值"""

    # 1. 渲染限制
    LIMIT_TASK: int = 2 # 最大并发编译数
    LIMIT_GIANT: int = 1500
    LIMIT_WEBP: int = 16383
    LIMIT_SIDE: int = 16000
    LIMIT_PPI: float = 144.0

    # 2. 超时设置 (秒)
    TIMEOUT_ANALYSIS: float = 10.0
    TIMEOUT_COMPILE: float = 30.0

    # 3. 过滤设置
    # config.py 负责 list → set
    IGNORED_PLUGINS: Set[str] = {
        "astrbot", 
        "astrbot-web-searcher", 
        "astrbot-python-interpreter",
        "session_controller",
        "builtin_commands",
        "astrbot-reminder", 
        "astrbot_plugin_help_typst"
    }


class RenderMode(str, Enum):
    """枚举"""
    COMMAND = "command"
    EVENT = "event"
    FILTER = "filter"