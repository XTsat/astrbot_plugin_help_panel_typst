from typing import List, Optional
from pydantic import BaseModel, Field

class RenderNode(BaseModel):
    """
    通用渲染节点：
    - 在指令模式下：代表 指令组 或 指令
    - 在事件模式下：代表 事件类型分组 或 具体Handler
    """
    name: str = Field(..., description="显示名称")
    desc: str = Field(default="", description="描述文本")

    # 样式控制字段
    is_group: bool = Field(default=False, description="是否为容器/分组")

    tag: str = Field(default="normal", description="标记类型: normal/admin/event")
    priority: Optional[int] = Field(default=None, description="事件监听优先级")
    children: List['RenderNode'] = Field(default_factory=list, description="子节点")

    class Config:
        use_enum_values = True

RenderNode.update_forward_refs()

class PluginMetadata(BaseModel):
    name: str = Field(..., description="插件ID")
    display_name: Optional[str] = Field(None, description="展示名称")
    version: Optional[str] = Field(None, description="版本号")
    desc: str = Field(default="")

    nodes: List[RenderNode] = Field(default_factory=list)