from typing import List, Optional, Any
from pydantic import BaseModel, Field, ConfigDict, field_validator

class RenderNode(BaseModel):
    """
    通用渲染节点：
    - 在指令模式下：代表 指令组 或 指令
    - 在事件模式下：代表 事件类型分组 或 具体Handler
    """
    model_config = ConfigDict(use_enum_values=True)

    name: str = Field(..., description="显示名称")
    desc: str = Field(default="", description="描述文本")

    # 样式控制字段
    is_group: bool = Field(default=False, description="是否为容器/分组")

    tag: str = Field(default="normal", description="标记类型: normal/admin/event")
    priority: Optional[int] = Field(default=None, description="事件监听优先级")

    # 递归定义
    children: List['RenderNode'] = Field(default_factory=list, description="子节点")

    # 验证器
    @field_validator('name', mode='before')
    @classmethod
    def ensure_string_name(cls, v: Any) -> str:
        return str(v) if v is not None else "Unknown"

    @field_validator('desc', mode='before')
    @classmethod
    def ensure_string_desc(cls, v: Any) -> str:
        return str(v) if v is not None else ""


class PluginMetadata(BaseModel):
    model_config = ConfigDict(
        use_enum_values=True,
        extra='ignore'  # 防御元信息垃圾
    )

    name: str = Field(..., description="插件ID")
    display_name: Optional[str] = Field(None, description="展示名称")
    version: Optional[str] = Field(None, description="版本号")
    desc: str = Field(default="")

    nodes: List[RenderNode] = Field(default_factory=list)

    @field_validator('name', mode='before')
    @classmethod
    def ensure_plugin_name(cls, v: Any) -> str:
        if v is None:
            return "Unknown_Plugin_ID"
        return str(v)

    @field_validator('version', mode='before')
    @classmethod
    def ensure_version(cls, v: Any) -> str:
        return str(v) if v is not None else ""

    @field_validator('desc', mode='before')
    @classmethod
    def ensure_desc(cls, v: Any) -> str:
        return str(v) if v is not None else ""