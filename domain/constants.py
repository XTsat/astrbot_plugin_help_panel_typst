from enum import Enum
from typing import Set, Dict

# --- A. 内部常量 (开发者专用，不暴露给用户) ---
class InternalCFG:
    """内部硬编码配置，用户无法修改"""
    # 资源文件映射
    CACHE_FILES: Dict[str, str] = {
        "command": "cache_menu_command",
        "event":   "cache_menu_event",
        "filter":  "cache_menu_filter"
    }
    # 字体/模板相对路径
    TEMPLATE_NAME: str = "base.typ"
    FONT_DIR_NAME: str = "fonts"

# --- B. 默认配置值 (作为 schema 的默认值兜底) ---
class DefaultCFG:
    """可配置项的默认值"""
    
    # 1. 渲染限制
    GIANT_THRESHOLD: int = 1500
    WEBP_LIMIT: int = 16383
    SPLIT_HEIGHT: int = 16000
    
    # 2. 超时设置 (秒)
    TIMEOUT_ANALYSIS: float = 10.0
    TIMEOUT_COMPILE: float = 30.0
    
    # 3. 过滤设置
    # 注意：JSON只支持 List，Python 逻辑里我们需要 Set，这里定义 Set 方便代码使用
    # 在 config.py 加载时会将 JSON 的 list 转回 set
    IGNORED_PLUGINS: Set[str] = {
        "astrbot", 
        "astrbot-web-searcher", 
        "astrbot-python-interpreter",
        "session_controller",
        "builtin_commands",
        "astrbot-reminder", 
        "astrbot_plugin_help_typst"
    }

# --- C. 枚举 ---
class RenderMode(str, Enum):
    COMMAND = "command"
    EVENT = "event"
    FILTER = "filter"