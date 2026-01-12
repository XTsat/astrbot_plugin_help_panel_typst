from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


# --- 复用的清洗逻辑 ---

def _coerce_to_string(v: Any) -> str:
    """将任意输入转为字符串, None 转为空字符串"""
    return str(v) if v is not None else ""

def _coerce_to_name(v: Any) -> str:
    """将任意输入转为字符串, None 转为 'Unknown'"""
    s = str(v) if v is not None else ""
    return s if s.strip() else "Unknown"

# --- 带有预处理能力的类型 ---

SafeStr = Annotated[str, BeforeValidator(_coerce_to_string)]
SafeName = Annotated[str, BeforeValidator(_coerce_to_name)]


class RenderNode(BaseModel):
    """
    通用渲染节点：
    - 在指令模式下：代表 指令组 或 指令
    - 在事件模式下：代表 事件类型分组 或 具体Handler
    """

    model_config = ConfigDict(
        use_enum_values=True,
        extra="ignore"  # 防御多余字段
    )

    name: SafeName = Field(..., description="显示名称")
    desc: SafeStr = Field(default="", description="描述文本")

    # 样式控制字段
    is_group: bool = Field(default=False, description="是否为容器/分组")
    tag: str = Field(default="normal", description="标记类型: normal/admin/event")
    priority: int | None = Field(default=None, description="事件监听优先级")

    # 递归定义
    children: list["RenderNode"] = Field(default_factory=list, description="子节点")


class PluginMetadata(BaseModel):
    """插件元数据容器"""
    model_config = ConfigDict(
        use_enum_values=True,
        extra="ignore"  # 防御元信息垃圾
    )

    name: SafeName = Field(..., description="插件ID")
    display_name: str | None = Field(default=None, description="展示名称")
    version: SafeStr = Field(default="", description="版本号")
    desc: SafeStr = Field(default="", description="描述")

    nodes: list[RenderNode] = Field(default_factory=list)
