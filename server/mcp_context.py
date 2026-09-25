from dataclasses import dataclass

from .tools import Principal

@dataclass(frozen=True)
class MCPPrincipal:
    # 这些字段由 Agent Host 的服务端会话创建；模型和浏览器参数不能覆盖它们。
    user_id: str
    role: str
    internal_authorized: bool
    session_id: str = ""
    request_id: str = ""
    tool_call_id: str = ""

    def to_tool_principal(self) -> Principal:
        # MCP Server 内部工具继续复用既有 Principal，避免出现两套权限实现。
        return Principal(self.user_id, self.role, self.internal_authorized)
