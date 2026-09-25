"""Minimal MCP-compatible JSON-RPC stdio server. stdout is protocol only."""
from __future__ import annotations
import json, sys, uuid
from .tools import registry
from .mcp_context import MCPPrincipal

# 显式白名单：禁止从 Python 模块、函数或用户输入自动生成工具。
EXPOSED = ("get_order_status","get_logistics_tracking","get_device_status","get_device_last_seen","assess_return_eligibility","create_service_ticket")

def tool_descriptors(principal=None):
    # 工具发现也按 Principal 过滤，模型只会看到当前身份可调用的工具。
    # 当前 EXPOSED 工具均为业务公开工具；内部资料不通过 MCP 工具暴露。
    # 未授权的售后二线仍可使用公开订单、物流和设备工具，内部授权只影响未来新增的受限工具。
    return [{"name": n, "description": registry[n].description, "inputSchema": registry[n].input_schema} for n in EXPOSED if principal is None or principal.role in registry[n].allowed_roles]

def call_tool(name, arguments, principal: MCPPrincipal):
    # Server 端再次校验名称、角色和授权，不能把 Client 的校验当作信任边界。
    if name not in EXPOSED: raise ValueError("unknown_tool")
    tool = registry[name]
    if principal.role not in tool.allowed_roles: raise ValueError("forbidden")
    # 拒绝额外字段，避免把隐藏控制项、SQL 片段或路径传入业务处理函数。
    if not isinstance(arguments, dict) or set(arguments) - set(tool.input_schema.get("properties", {})):
        raise ValueError("invalid_arguments")
    result = tool.execute(arguments, principal.to_tool_principal(), principal.tool_call_id or uuid.uuid4().hex)
    return {"ok": result.ok, "toolName": result.toolName, "toolCallId": result.requestId, "data": result.data if result.ok else {}, "userMessage": result.userMessage, "errorCode": result.errorCode, "needHuman": result.needHuman}

def handle(req):
    method, params = req.get("method"), req.get("params") or {}
    if method == "initialize": return {"protocolVersion":"2024-11-05","capabilities":{"tools":{"listChanged":False}},"serverInfo":{"name":"x100-mcp","version":"1.0"}}
    if method == "notifications/initialized": return None
    if method == "tools/list":
        p = MCPPrincipal(str(params.get("userId","")), str(params.get("role","user")), bool(params.get("internalAuthorized",False)))
        return {"tools": tool_descriptors(p)}
    if method == "tools/call":
        p = MCPPrincipal(str(params.get("userId","")), str(params.get("role","user")), bool(params.get("internalAuthorized",False)), str(params.get("sessionId","")), str(params.get("requestId","")), str(params.get("toolCallId","")))
        result = call_tool(params.get("name",""), params.get("arguments") or {}, p)
        return {"content":[{"type":"text","text":json.dumps(result, ensure_ascii=False)}],"structuredContent":result,"isError":not result["ok"]}
    raise ValueError("method_not_found")

def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="strict")
    for line in sys.stdin:
        req = {}
        try:
            # stdout 只输出 JSON-RPC；诊断信息应写 stderr，避免破坏协议帧。
            req=json.loads(line); response=handle(req)
            if req.get("id") is not None and response is not None: print(json.dumps({"jsonrpc":"2.0","id":req["id"],"result":response},ensure_ascii=False),flush=True)
        except Exception as exc:
            if req.get("id") is not None: print(json.dumps({"jsonrpc":"2.0","id":req["id"],"error":{"code":-32600,"message":str(exc)}},ensure_ascii=False),flush=True)
if __name__ == "__main__": main()
