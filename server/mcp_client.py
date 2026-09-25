from __future__ import annotations
import json, os, subprocess, sys, threading, uuid, queue
from .mcp_context import MCPPrincipal

class MCPClientError(Exception): pass
class MCPClient:
    def __init__(self):
        self.enabled=os.getenv("MCP_ENABLED","1") == "1"; self.proc=None; self.lock=threading.Lock(); self.tools={}
        self.timeout=float(os.getenv("MCP_TOOL_TIMEOUT_SECONDS","20"))
    def _start(self):
        if self.proc: return
        # 命令固定为当前 Python 的 server.mcp_server，绝不拼接用户或模型输入。
        self.proc=subprocess.Popen([sys.executable,"-m","server.mcp_server"],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding="utf-8",bufsize=1)
        self._rpc("initialize",{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"x100-agent","version":"1.0"}})
        self.proc.stdin.write(json.dumps({"jsonrpc":"2.0","method":"notifications/initialized","params":{}})+"\n"); self.proc.stdin.flush()
    def _rpc(self, method, params):
        with self.lock:
            if not self.proc or self.proc.poll() is not None: raise MCPClientError("mcp_disconnected")
            ident=uuid.uuid4().hex; self.proc.stdin.write(json.dumps({"jsonrpc":"2.0","id":ident,"method":method,"params":params})+"\n"); self.proc.stdin.flush()
            # readline 本身可能阻塞；用守护线程包住读取并设置工具级超时。
            box=queue.Queue(maxsize=1)
            threading.Thread(target=lambda: box.put(self.proc.stdout.readline()), daemon=True).start()
            try: line=box.get(timeout=self.timeout)
            except queue.Empty:
                self.close(); raise MCPClientError("mcp_timeout")
            if not line: raise MCPClientError("mcp_disconnected")
            try: data=json.loads(line)
            except (TypeError, ValueError): raise MCPClientError("mcp_protocol_error")
            if "error" in data: raise MCPClientError("mcp_protocol_error")
            return data.get("result")
    def list_tools(self, principal):
        # 每次发现都带上可信 Principal，Server 会重新做角色过滤。
        if not self.enabled: return []
        self._start(); result=self._rpc("tools/list",{"userId":principal.user_id,"role":principal.role,"internalAuthorized":principal.internal_authorized}); self.tools={x["name"]:x for x in result.get("tools",[])}; return list(self.tools.values())
    def call_tool(self,name,arguments,principal,request_id):
        if not self.enabled: raise MCPClientError("mcp_disabled")
        self._start()
        # 本地白名单先挡住未知工具，再发送到 MCP Server。
        if name not in {x["name"] for x in self.list_tools(principal)}: raise MCPClientError("unknown_tool")
        return self._rpc("tools/call",{"name":name,"arguments":arguments,"userId":principal.user_id,"role":principal.role,"internalAuthorized":principal.internal_authorized,"requestId":request_id,"toolCallId":uuid.uuid4().hex}).get("structuredContent")
    def close(self):
        # 关闭时回收子进程和管道，避免开发重载留下悬挂 MCP Server。
        if self.proc:
            proc, self.proc = self.proc, None
            proc.terminate()
            try: proc.wait(timeout=2)
            except subprocess.TimeoutExpired: proc.kill(); proc.wait(timeout=2)
            for stream in (proc.stdin, proc.stdout):
                try: stream.close()
                except Exception: pass
