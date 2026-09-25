# X100 MCP 整改自检报告

## 已施工

- `server/mcp_server.py` 提供固定六工具白名单、JSON-RPC initialize、tools/list、tools/call 和结构化脱敏结果。
- `server/mcp_client.py` 仅启动固定的 `python -m server.mcp_server` 子进程，处理请求 ID、工具调用 ID、断开和协议错误。
- `server/mcp_context.py` 定义服务端 Principal；Agent 调用工具时由会话身份构造，模型参数不能覆盖。
- `server/agent.py` 的读写工具执行均经过 MCP Client；写工具仍先生成一次性确认单，确认后才调用 MCP。
- `src/App.tsx` 展示 Agent 阶段、MCP 工具摘要、RAG 来源，并通过 `/api/agent/confirm` 完成确认或取消。

## 启动方式

```powershell
pnpm dev
```

浏览器访问 `http://127.0.0.1:5173/`，API 为 `http://127.0.0.1:8005/`。`pnpm dev` 不会预先单独启动 MCP Server；Agent Host 在首次工具调用时自动启动固定的 `python -m server.mcp_server` 子进程。只有协议调试才直接运行 `python -m server.mcp_server`，浏览器不连接该进程。

## 安全边界

工具名必须命中六项白名单，额外参数会被拒绝；MCP Server 再检查角色、内部授权、资源归属和参数格式。工具结果只包含最小业务字段，失败只返回安全错误码和人工转接标记。MCP 关闭时可通过 `MCP_ENABLED=0` 使用兼容回退。

## 验证记录

```text
python -m unittest discover -s server/tests -v  # 26 tests, OK
python -m server.mcp_server                    # initialize/list_tools/call_tool 已手工验证
pnpm build                                      # tsc + vite build OK
python -m compileall -q server                  # OK
```

本地 stdio 实现遵循 MCP JSON-RPC tools 子集，未引入额外 SDK 依赖；传输固定为本机子进程，便于当前离线 Demo 的可重复部署。

## 复核补充（2026-09-25）

- 复核发现并修正：未授权售后二线仍应能使用公开订单、物流和设备工具，只有未来新增的受限工具才需要内部授权；已在 `server/mcp_server.py` 和 `server/tests/test_mcp.py` 中补齐。
- 修正后 `pnpm test:core` 为 26 项通过，`pnpm build` 和 Python 编译检查通过。
- 当前 MCP 是本地 stdio 的 MCP-compatible JSON-RPC 子集，尚未引入完整 MCP SDK；如需与外部 MCP 客户端互操作，应补充官方 SDK、协议兼容测试和认证传输。
- 当前 Agent 仍以一次路由和一次工具执行为主；`MAX_AGENT_STEPS`、`MAX_TOOL_CALLS` 尚未形成完整的多轮工具调用循环，DeepSeek 路由仍使用受限 JSON 兼容方式。后续若要求完整 Agent Loop，需要继续改造 `server/agent.py` 和 `server/llm.py`。
- 当前 MCP Principal 通过本机子进程参数传递，适合本地 Demo；远程 MCP 或生产部署必须增加认证、签名或受保护的服务间通道。
