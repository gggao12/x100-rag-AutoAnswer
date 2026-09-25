from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable
import hashlib, json, re, uuid

# Principal 由服务端会话构造；前端和模型传入的 role 不参与权限计算。
@dataclass(frozen=True)
class Principal:
    user_id: str = "demo-user"
    role: str = "user"
    internal_authorized: bool = False

@dataclass
class ToolResult:
    ok: bool
    toolName: str
    requestId: str
    data: dict[str, Any]
    userMessage: str
    errorCode: str | None = None
    needHuman: bool = False
    def as_dict(self): return self.__dict__.copy()

# 所有工具先经过统一权限和参数边界，再进入具体业务处理函数。
class Tool:
    def __init__(self, name: str, description: str, input_schema: dict, risk_level: str, allowed_roles: tuple[str, ...], handler: Callable):
        self.name, self.description, self.input_schema, self.risk_level = name, description, input_schema, risk_level
        self.allowed_roles, self._handler = allowed_roles, handler
    def execute(self, arguments: dict, principal: Principal, request_id: str | None = None) -> ToolResult:
        rid = request_id or uuid.uuid4().hex
        if principal.role not in self.allowed_roles:
            return ToolResult(False, self.name, rid, {}, "当前身份无权使用此工具", "forbidden", True)
        # 拒绝额外字段，避免模型借参数注入 SQL、路径或未声明控制项。
        if not isinstance(arguments, dict) or set(arguments) - set(self.input_schema.get("properties", {})):
            return ToolResult(False, self.name, rid, {}, "工具参数不符合要求", "invalid_arguments", True)
        try: return self._handler(arguments, principal, rid)
        except Exception: return ToolResult(False, self.name, rid, {}, "工具执行失败，请转人工", "tool_error", True)

def parameter_hash(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
def valid_order_id(v): return isinstance(v, str) and bool(re.fullmatch(r"ORD-DEMO-\d{4}", v))
def valid_sn(v): return isinstance(v, str) and bool(re.fullmatch(r"X100-DEMO-\d{4}", v))
